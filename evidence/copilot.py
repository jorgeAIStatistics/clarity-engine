"""Question-aware, record-grounded research navigation. No model or agreement verdict.

Intent fields preserve excerpts of the submitted question. Evidence groups organize
retained records, not inferred clinical truth; missing means missing in this retrieval.
"""
import re
from collections import Counter

ANGLES={
 'association':{'label':'Association & risk','pattern':r'associat|correlat|risk|prognos|biomarker','question':'How does the marker relate to the outcome?','guidance':'Compare adjustment sets, baseline disease and follow-up. An association estimate does not identify an effective management strategy.'},
 'incremental':{'label':'Discordance & incremental value','pattern':r'discordan|incremental|reclassif|predict|discriminat|added value','question':'Does the marker add information beyond the existing model?','guidance':'Read the comparator model and C-index or reclassification metric before comparing estimates. Check external validation and calibration.'},
 'utility':{'label':'Clinical utility & management','pattern':r'clinical utility|clinical benefit|decision|management|actionab|screening benefit','question':'Does acting on this information improve outcomes?','guidance':'Look for a comparison of marker-guided management strategies. A drug trial in a marker-selected group answers a different question.'},
 'treatment':{'label':'Intervention outcomes','pattern':r'interven|treatment|therap|efficacy|dose|survival|random','question':'Which interventions and endpoints have been compared?','guidance':'Check treatment setting, dose, comparator, endpoint and crossover. Keep follow-up reports from the same trial together.'},
 'accuracy':{'label':'Test accuracy & measurement','pattern':r'accuracy|sensitiv|specific|diagnos|assay|measurement','question':'How was the measurement or test evaluated?','guidance':'Check the assay, threshold and reference standard. Accuracy is distinct from improvement in patient outcomes.'},
 'guidelines':{'label':'Guidelines & consensus','pattern':r'guideline|consensus|regulat|recommendation','question':'What framing comes from guidance or consensus?','guidance':'Read the source date, scope and recommendation process. Consensus is not an additional randomized comparison.'}
}
BROAD=set('health human humans adults adult patients study studies research evidence result results outcome outcomes biomarker biomarkers marker markers clinical value data topic context focus focusing studying difference differ how strength utility association associations event events effect effects benefit disease'.split())

def excerpts(text,pattern):
 return list(dict.fromkeys(m.group(0).strip() for m in re.finditer(pattern,text,re.I)))[:6]

def understand(text,entities):
 population=excerpts(text,r'\b(?:adults?(?:\s+(?:with|without)\s+[^,;.\n]{1,65})?|children|adolescents|postmenopausal women|older adults|healthy volunteers)\b')
 mapped=excerpts(text,r'(?<=context: )[^;\n]+')
 outcomes=excerpts(text,r'(?<=outcome: )[^;\n]+') or excerpts(text,r'\b(?:cardiovascular events|coronary heart disease|overall survival|progression[- ]free survival|disease[- ]free survival|mortality|diabetes(?: diagnosis)?|kidney function|cognition|muscle strength|fractures)\b')
 requested=[key for key,a in ANGLES.items() if re.search(a['pattern'],text,re.I)]
 if not requested:requested=['association' if any(e['entity_type']=='biomarker' for e in entities) else 'treatment']
 return {'population':population,'outcomes':outcomes,'context':mapped,'focus':[{'id':a,'label':ANGLES[a]['label']} for a in requested],
         'primary_concepts':[{'id':e['id'],'name':e['name'],'path':e['path']} for e in entities if e.get('matched_aliases')],
         'secondary_concepts':[{'id':e['id'],'name':e['name'],'path':e['path']} for e in entities if not e.get('matched_aliases')],
         'status':'automated_interpretation','restatement':(' × '.join([e['name'] for e in entities if e.get('matched_aliases')]+outcomes[:2])+'. '+('Population: '+', '.join(population) if population else 'Population not specified')+'. Focus: '+', '.join(ANGLES[a]['label'].lower() for a in requested)+'.') if any(e.get('matched_aliases') for e in entities) else 'No named entity was recognized in your text; the records shown match its wording only.',
         'note':'A structured reading of your text, not a validated study protocol. Edit the input if the scope is incomplete.'}

def record_angles(study):
 text=(study.get('title','')+' '+study.get('_text','')).lower();layer=study.get('layer');result=[]
 if layer=='observational' or (layer=='synthesis' and re.search(r'cohort|observational|prospective',text)):result.append('association')
 if re.search(r'discordan|reclassif|c.index|incremental|discriminat|predictive value',text):result.append('incremental')
 # Classify as a candidate management-strategy record only with explicit design framing.
 if layer=='interventional' and re.search(r'(?:biomarker|marker|test)[- ]guided|screening strateg|screening invitation|invitation to.*screen',text):result.append('utility')
 if layer=='interventional' or (layer=='synthesis' and re.search(r'randomi[sz]ed trials?|statin trials?',text)):result.append('treatment')
 if re.search(r'specificity|diagnostic accuracy|analytical validity|assay validation|pooled sensitivity',text):result.append('accuracy')
 if layer=='guidelines':result.append('guidelines')
 return result

def landscape(text,entities,studies,all_entities):
 question=understand(text,entities);requested=[a['id'] for a in question['focus']]
 groups=[]
 active=list(dict.fromkeys(requested+[a for s in studies for a in s.get('angles',[])]))
 for angle in active:
  spec=ANGLES[angle];records=[s for s in studies if angle in s.get('angles',[])]
  findings=[]
  for s in records:
   # Quantitative statements are literal structured source extracts, not inferred effects.
   for f in s.get('findings',[]):
    measure=str(f.get('effect',{}).get('measure','')).lower()
    if angle=='incremental' and not re.search(r'c.index|reclassif|auc|discriminat|residual|discordan',measure+' '+str(f.get('exposure',''))):continue
    if angle=='association' and re.search(r'c.index|reclassif|auc|discriminat',measure):continue
    if angle=='accuracy' and not re.search(r'sensitiv|specific|accuracy|predictive value',measure):continue
    if f.get('quote') and f.get('effect'):
     findings.append({'study_id':s['id'],'outcome':f['outcome'],'effect':f['effect'],'quote':f['quote'],'population':f.get('population') or s.get('population'),'exposure':f.get('exposure') or s.get('exposure'),'comparator':f.get('comparator') or s.get('comparator'),'cohort':s.get('cohort_id'),'review_status':s['review_status']})
  endpoint_terms=set(re.findall(r'[a-z]{4,}', ' '.join(question['outcomes']).lower()))
  if 'cardiovascular' in endpoint_terms:endpoint_terms.update({'coronary','stroke','cvd'})
  findings.sort(key=lambda f:len(endpoint_terms & set(re.findall(r'[a-z]{4,}',f['outcome'].lower()))),reverse=True)
  ids=[s['id'] for s in records]
  groups.append({'id':angle,'label':spec['label'],'requested':angle in requested,'question':spec['question'],'study_ids':ids,
   'status':'records_to_appraise' if ids else 'retrieval_gap','summary':f'{len(ids)} retrieved publication records address this research angle; applicability and appraisal remain to be checked.' if ids else 'No matching record was retrieved for this angle. This does not establish a gap in the full literature.',
   'interpretation':('The retained findings report '+', '.join(dict.fromkeys(f['effect']['measure'] for f in findings))+'. Keep these measures tied to their populations and comparators; they are not interchangeable.' if findings else 'This angle has source context but no structured numerical finding in the retrieved records.' if ids else 'A direct answer to this part of the question remains unresolved in the retrieved library.'),
   'findings':findings[:4],'guidance':spec['guidance'],'requires_review':True})
 tensions=[]
 if 'association' in requested and 'utility' in requested:
  tensions.append({'title':'Association and utility need different comparisons','text':'Compare the observational marker estimates with actual marker-guided management comparisons. Treatment results alone do not resolve whether measuring a marker improves decisions.','study_ids':[s['id'] for s in studies if set(s.get('angles',[]))&{'association','treatment','utility'}],'status':'review_question'})
 cohorts=Counter(s.get('cohort_id') for s in studies if s.get('cohort_id'))
 if any(n>1 for n in cohorts.values()):tensions.append({'title':'Reports may share participants','text':'These records name the same cohort or trial. Check participant overlap before treating their estimates as independent.','study_ids':[s['id'] for s in studies if cohorts[s.get('cohort_id')]>1],'status':'record_metadata'})
 if any(s.get('layer')=='guidelines' for s in studies):tensions.append({'title':'Consensus framing is a separate layer','text':'Compare guidance with the underlying study populations and endpoints before transferring it to this question.','study_ids':[s['id'] for s in studies if s['layer']=='guidelines'],'status':'review_question'})
 gaps=[{'id':g['id'],'label':g['label'],'text':g['summary']} for g in groups if g['requested'] and not g['study_ids']]
 if not question['population']:gaps.append({'id':'population','label':'Population unspecified','text':'Add the intended population or setting to distinguish otherwise similar evidence.'})
 if not question['outcomes']:gaps.append({'id':'outcomes','label':'Endpoint needs clarification','text':'No endpoint was recognized in the text. Name the outcome you want to compare.'})
 guidance=[{'title':g['label'],'text':g['guidance'],'study_ids':g['study_ids'][:2],'priority':'Read first' if g['requested'] and g['study_ids'] else 'Next search' if not g['study_ids'] else 'Related angle'} for g in groups]
 by={e['id']:e for e in all_entities};selected={e['id'] for e in entities};bridges=[]
 for e in entities:
  for target in e.get('related_ids',[]):
   other=by.get(target)
   if other and other['entity_type']!=e['entity_type'] and len(bridges)<8:
    key=(e['id'],target)
    if not any((b['from_id'],b['to_id'])==key for b in bridges):bridges.append({'from_id':e['id'],'from_name':e['name'],'to_id':target,'name':other['name'],'path':other['path'],'entity_type':other['entity_type'],'in_results':target in selected,'relationship':'Catalog research connection; not a clinical interaction claim'})
 matrix=[{'entity_id':e['id'],'name':e['name'],'path':e['path'],'cells':[{'angle':g['id'],'count':sum(e['id'] in s['entity_ids'] and g['id'] in s.get('angles',[]) for s in studies)} for g in groups]} for e in entities]
 return {'question':question,'groups':groups,'tensions':tensions,'gaps':gaps,'guidance':guidance,'landscape':matrix,'bridges':bridges,'scope':'Provisional, deterministic organization of retained records. No pooled estimate, support/contradiction verdict or clinical recommendation.'}
