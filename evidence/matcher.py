"""Bounded, source-grounded literature navigation without paid model calls.

Phase 1: entity aliases + biomedical concept expansion + lexical ranking.
Retrieval rank is not scientific agreement, a clinical grade, or a probability.
The query is processed in memory and never written to state or model providers.
"""
import math
import html
import re
import threading
from collections import Counter
from functools import lru_cache
from .service import CATALOG
from .profile import layer_for

VERSION='evidence-copilot-v3'
STOP=set('the a an and or of to in for with by as is was were be been on from at this that we our study studies patients results methods abstract introduction'.split())
CONCEPTS=[('apob','apolipoprotein b'),('hba1c','glycated hemoglobin','glycated haemoglobin','hemoglobin a1c'),('ldl c','ldl cholesterol','low density lipoprotein cholesterol'),('non hdl c','non hdl cholesterol'),('cystatin c','cystatin c based egfr'),('hs crp','high sensitivity c reactive protein'),('psa','prostate specific antigen'),('rct','randomized controlled trial','randomised controlled trial')]

def research_input_error(text):
    if re.search(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b(?:patient|participant|subject)[ _-]*(?:id|identifier|name)\b|\b(?:mrn|ssn|date[ _-]*of[ _-]*birth|dob|first[ _-]*name|last[ _-]*name|phone[ _-]*number|home[ _-]*address)\b', text, re.I):
        return 'Patient identifiers or contact fields detected. Use aggregate research content without identifying fields.'
    if re.search(r'\b(?:my|your)\s+(?:blood|lab|test|medical|health)\s*(?:results?|values?|tests?|records?|report)?\b|\bwhat\s+(?:should|can)\s+i\s+take\b',text,re.I):
        return 'Personal-health interpretation is outside this tool. Use a study description or aggregate research results.'
    return ''

def normalize(text):return re.sub(r'[^a-z0-9]+',' ',str(text).lower()).strip()
def tokens(text):return set(normalize(text).split())-STOP

def expanded_tokens(text):
    normalized=' '+normalize(text)+' '
    result=tokens(text)
    for aliases in CONCEPTS:
        if any(' '+normalize(alias)+' ' in normalized for alias in aliases):
            for alias in aliases:result.update(tokens(alias))
    if ' egfr ' in normalized:
        if result & {'kidney','renal','creatinine','cystatin','glomerular'}:result.update(tokens('estimated glomerular filtration rate'))
        elif result & {'cancer','nsclc','mutation','mutated','osimertinib','tumor'}:result.update(tokens('epidermal growth factor receptor'))
    return result

def documents(profiles):
    entities=[];studies={}
    for profile in profiles:
        compound=profile.get('entity_type','intervention')=='intervention'
        kind=profile.get('entity_type','intervention')
        if compound:
            import cache
            key='compound:'+cache._slug(profile['name']);path='/compound/'+cache._slug(profile['name'])
            outcomes=profile.get('claims',[])
            records=[s for o in outcomes for s in o.get('studies',[])]
        else:
            paths={'biomarker':'biomarkers','diagnostic':'diagnostics','screening':'screening','precision_oncology':'precision-medicine'}
            key='entity:'+profile['id'];path='/'+paths[kind]+'/'+profile['id'];outcomes=profile.get('outcomes',[]);records=profile.get('studies',[])
        names=[profile['name'],*profile.get('aliases',[])]
        outcome_names=[o.get('name') or o.get('outcome','') for o in outcomes]
        text=' '.join([*names,profile.get('summary',''),*outcome_names,*profile.get('conditions',[])])
        entities.append({'id':key,'name':profile['name'],'entity_type':kind,'path':path,'aliases':names,'outcomes':outcome_names,'_text':text,'_tokens':tokens(text),'study_count':len(records),'review_status':profile.get('review_status','automated_appraisal' if compound else 'reference_summary'),'maturity':profile.get('display_tier') or profile.get('tier') or ('Human evidence indexed' if records else 'Reference context'),'related_ids':['entity:'+r for r in profile.get('related',[])]+['compound:'+r['path'].split('/')[-1] for r in profile.get('related_interventions',[]) if r.get('path')],'record_density':{'quantified_findings':sum(len(s.get('findings',[])) for s in records)}})
        for source in records:
            pmid=source.get('pmid');doi=source.get('doi')
            url=source.get('url') or (f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else '')
            if not url.startswith('https://'):continue
            identity='pmid:'+str(pmid) if pmid else 'doi:'+str(doi).lower() if doi else source.get('id') or url
            if identity not in studies:
                title=source.get('title','');abstract=source.get('abstract') or source.get('quote') or ''
                abstract=html.unescape(re.sub(r'</?(?:h[1-6]|p|div|span|b|i|em|strong|sup|sub|br)\b[^>]*>', ' ',abstract,flags=re.I)).strip()
                studies[identity]={'id':identity,'title':title,'url':url,'pmid':pmid,'design':source.get('design') or source.get('study_type'),
                    'population':source.get('population'),'n':source.get('n'),'layer':layer_for(source),'findings':[],'exposure':source.get('exposure'),'comparator':source.get('comparator'),'cohort_id':source.get('cohort_id'),'entity_ids':[],
                    '_passages':[f['quote'] for f in source.get('findings',[]) if f.get('quote') and f['quote'] in abstract], '_text':abstract,'_tokens':tokens(title+' '+abstract), 'agreement':'not_assessed','review_status':source.get('review_status','not_recorded')}
            record=studies[identity]
            for finding in source.get('findings',[]):
                if not finding.get('quote') or finding['quote'] not in record['_text']:continue
                existing=next((f for f in record['findings'] if f['outcome']==finding['outcome'] and f['effect']==finding['effect']),None)
                if existing:
                    if key not in existing['entity_ids']:existing['entity_ids'].append(key)
                else:record['findings'].append({**finding,'entity_ids':[key],'population':source.get('population'),'exposure':source.get('exposure'),'comparator':source.get('comparator')})
            if key not in record['entity_ids']:record['entity_ids'].append(key)
    counts=Counter(entity_id for s in studies.values() for entity_id in s['entity_ids'])
    by_id={e['id']:e for e in entities}
    for entity in entities:
        entity['study_count']=counts[entity['id']]
        for related in list(entity['related_ids']):
            if related in by_id and entity['id'] not in by_id[related]['related_ids']:by_id[related]['related_ids'].append(entity['id'])
    from .copilot import record_angles
    for study in studies.values():study['angles']=record_angles(study)
    return entities,list(studies.values())

_index_lock=threading.Lock()

def library_index(bucket):
    with _index_lock:return _library_index(bucket)

@lru_cache(maxsize=1)
def _library_index(bucket):
    import cache
    from .enrichment import enriched_profile
    def profiles():
        yield from CATALOG['entities']
        seen=set()
        for _,profile in cache.iter_profiles():
            if isinstance(profile,dict) and profile.get('name') and profile.get('claims') and profile['name'] not in seen:
                seen.add(profile['name'])
                yield enriched_profile(profile)
    return documents(profiles())

def passage(text,query):
    if not text:return None
    spans=list(re.finditer(r'.+?(?:[.!?](?=\s|$)|\n|$)',text,re.S))
    best=max(spans,key=lambda m:len(tokens(m.group())&query),default=None)
    if not best:return None
    start=best.start();end=min(best.end(),start+500)
    return {'text':text[start:end],'start':start,'end':end,'basis':'retained source text with presentation markup removed and HTML entities decoded','truncated':end<best.end()}

def match(text,index,limit=8):
    if not isinstance(text,str) or not 20<=len(text.strip())<=12000:raise ValueError('Enter between 20 and 12,000 characters of research text.')
    if research_input_error(text):raise ValueError(research_input_error(text))
    query=expanded_tokens(text)
    if not query:raise ValueError('Include a research topic or entity name.')
    entities,studies=index;all_docs=entities+studies
    frequency=Counter(token for doc in all_docs for token in doc['_tokens'])
    def score(doc):return sum(math.log(1+len(all_docs)/(1+frequency[t])) for t in doc['_tokens']&query)/math.sqrt(max(1,len(doc['_tokens'])))
    from .copilot import BROAD,ANGLES,landscape
    normalized=' '+normalize(text)+' '
    informative=query-BROAD
    requested={k for k,a in ANGLES.items() if re.search(a['pattern'],text,re.I)}
    entity_matches=[]
    for e in entities:
        exact=[a for a in e['aliases'] if ' '+normalize(a)+' ' in normalized]
        # EGFR (oncology) and eGFR (kidney function) share spelling, not meaning.
        oncology=bool(query & {'cancer','nsclc','tumor','mutation','mutated','osimertinib'})
        renal=bool(query & {'kidney','renal','creatinine','cystatin','glomerular'})
        if normalize(' '.join(exact))=='egfr' and ((e['id']=='entity:creatinine-egfr' and oncology and not renal) or (e['entity_type']=='precision_oncology' and renal and not oncology)):exact=[]
        overlap=e['_tokens']&informative
        # Broad health words alone cannot create an entity match.
        value=score(e)+(10 if exact else 0) if exact or len(overlap)>=2 else 0
        if e['id']=='entity:creatinine-egfr' and oncology and not renal and not exact:value=0
        if value>0:entity_matches.append((value,e,exact))
    entity_matches.sort(key=lambda r:(-r[0],r[1]['name']))
    primary_ids={e['id'] for _,e,exact in entity_matches if exact}
    related_ids={r for _,e,exact in entity_matches if exact for r in e.get('related_ids',[])}
    if primary_ids:
        entity_matches=[row for row in entity_matches if row[1]['id'] in primary_ids or (row[1]['id'] in related_ids and len(row[1]['_tokens']&informative)>=2)]
    if primary_ids and all(e['entity_type']=='biomarker' for _,e,exact in entity_matches if exact) and 'treatment' not in requested:
        entity_matches=[row for row in entity_matches if row[1]['entity_type']!='intervention' or row[2]]
    selected=entity_matches[:limit]
    matched_ids={e['id'] for _,e,_ in selected}
    source_matches=[]
    for s in studies:
        overlap=s['_tokens']&query
        linked=matched_ids.intersection(s['entity_ids'])
        if s['layer']=='protocol':continue
        if matched_ids and not linked:continue
        if not linked and len(s['_tokens']&informative)<2:continue
        intent_bonus=2*len(requested.intersection(s.get('angles',[])))
        population_bonus=1 if ('adults' in query or 'adult' in query) and 'adult' in str(s.get('population','')).lower() else 0
        value=score(s)+(3 if primary_ids.intersection(s['entity_ids']) else 1 if linked else 0)+intent_bonus+population_bonus+(1 if s.get('findings') else 0)
        if overlap and value>0:source_matches.append((value,s))
    source_matches.sort(key=lambda r:(-r[0],r[1]['id']))
    # Reserve relevant records for each requested angle and named concept before filling by rank.
    chosen=[]
    for angle in sorted(requested):
        candidate=next((row for row in source_matches if angle in row[1].get('angles',[]) and row not in chosen),None)
        if candidate:chosen.append(candidate)
    for entity_id in sorted(primary_ids):
        candidate=next((row for row in source_matches if entity_id in row[1]['entity_ids'] and row not in chosen),None)
        if candidate:chosen.append(candidate)
    for row in source_matches:
        if len(chosen)>=12:break
        if row not in chosen:chosen.append(row)
    chosen.sort(key=lambda row:-row[0])
    def public(doc):return {k:v for k,v in doc.items() if not k.startswith('_')}
    def source_passage(source):
        relevant=[f for f in source.get('findings',[]) if set(f['entity_ids']) & (primary_ids if primary_ids.intersection(source['entity_ids']) else matched_ids)]
        quotes=[f['quote'] for f in relevant] or source.get('_passages',[])
        if not quotes:return passage(source['_text'],query)
        quote=max(quotes,key=lambda q:len(tokens(q)&query))
        start=source['_text'].index(quote)
        return {'text':quote,'start':start,'end':start+len(quote),'basis':'retained quote-backed finding','truncated':False}
    results=[{**public(s),'score':round(v,3),'matched_terms':sorted(s['_tokens']&query)[:12],'passage':source_passage(s),'findings':[f for f in s.get('findings',[]) if set(f['entity_ids']) & (primary_ids if primary_ids.intersection(s['entity_ids']) else matched_ids)]} for v,s in chosen[:12]]
    gaps=[]
    if not results:gaps.append('No retained study passages matched. Search the original literature before concluding that evidence is absent.')
    for field,label in [('population','Population'),('n','Sample size')]:
        missing=sum(not s.get(field) for s in results)
        if missing:gaps.append(f'{label} is missing in {missing} of {len(results)} retrieved source records.')
    gaps.append('Supporting versus contradicting evidence requires matching population, comparator, outcome and time horizon; it is not inferred from text similarity.')
    public_entities=[{**public(e),'score':round(v,3),'matched_aliases':exact,'matched_terms':sorted(e['_tokens']&query)[:12],
      'why':('Named research concept; ranked with your outcomes and requested evidence angles.' if exact else 'Catalog-linked context sharing specific terms with your research question.')} for v,e,exact in selected]
    copilot=landscape(text,public_entities,results,entities)
    for entity in public_entities:
        linked=[s for s in results if entity['id'] in s['entity_ids']]
        angle_labels=list(dict.fromkeys(a['label'] for a in copilot['groups'] if any(a['id'] in s.get('angles',[]) for s in linked)))
        entity['why']=('Named in your question. ' if entity['matched_aliases'] else 'Connected through the catalog graph. ')+(('Retrieved records cover '+', '.join(angle_labels[:3]).lower()+'.') if angle_labels else 'No classified source angle in this retrieval; inspect the profile for context.')
    return {'copilot':copilot,'version':VERSION,'method':'Explicit question fields, evidence-angle classification, linked-entity constraints, population cues and lexical relevance with angle diversity; deterministic and provisional. No embedding model or LLM calls.',
        'coverage':{'entities':len(entities),'studies':len(studies)},'entities':public_entities,
        'studies':results,'gaps':gaps,'related_questions':[f'Which populations and outcomes have been studied for {e["name"]}?' for _,e,_ in selected[:3]],
        'agreement_assessment':{'status':'requires_review','supporting':[],'contradicting':[],'note':'Interpretation remains provisional; no automatic agreement judgment is made.'},'query_stored':False}
