"""Deterministic interpretation of retained study-level extractions.

No new meta-analysis, participant summation, inferred benefit, or generated prose.
Every numerical interpretation retains the extracted passage and study identity.
"""
import math
import re
from .profile import layer_for

VERSION='study-analysis-v1'
MEASURES={'mean_diff':'Mean difference','smd':'Standardized mean difference','hr':'Hazard ratio','rr':'Risk ratio','or':'Odds ratio','risk_diff':'Risk difference'}
RATIOS={'hr','rr','or'}

def finite(value):return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)

def study_id(study):
    return str(study.get('pmid') or str(study.get('id','')).removeprefix('pmid:').removeprefix('PMID:') or study.get('url',''))

def numerical_tokens(text):
    return [float(n.replace(',','').replace('−','-')) for n in re.findall(r'(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?',text)]

def context_signals(study):
    """Retain exact contextual mentions, not inferred trial eligibility/regimens."""
    source=(study.get('title') or '')+'\n'+(study.get('abstract') or '')
    patterns={
        'population':r'\b(?:postmenopausal women|older (?:adults|women|men)|healthy (?:adults|volunteers|individuals|men|women)|resistance[- ]trained (?:athletes|adults|men|women)|professional (?:cyclists|athletes)|children|adolescents|patients with [\w -]{3,50})\b',
        'exposure':r'\b\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*(?:mg|g|µg|mcg)(?:\s*/\s*(?:kg|day|d)|\s+(?:daily|per day)|[·.]day[⁻−-]¹)',
        'follow_up':r'\b\d+(?:\s*[–-]\s*\d+)?[- ](?:weeks?|months?|years?)\b',
    }
    output={}
    for field,pattern in patterns.items():
        matches=list(re.finditer(pattern,source,re.I))[:3]
        if matches:output[field]=[{'text':m.group(),'start':m.start(),'end':m.end(),'source':'title_and_retained_abstract'} for m in matches]
    return output

def analyse_effect(effect,studies):
    reason=None
    study=studies.get(str(effect.get('pmid')))
    quote=effect.get('quote') or ''
    values=[effect.get(k) for k in ('value','ci_low','ci_high')]
    metric=effect.get('metric')
    if effect.get('ci_estimated') or effect.get('converted') or effect.get('status')!='verified':reason='Derived, converted, or unverified extraction'
    elif not study:reason='No matching study record in this outcome'
    elif layer_for(study)=='protocol' or study.get('is_preprint'):reason='Protocol or preprint; excluded from the quantitative reading'
    elif metric not in MEASURES:reason='Effect measure has not been normalized'
    elif not all(finite(v) for v in values):reason='Reported interval is incomplete'
    elif not values[1]<=values[0]<=values[2]:reason='Estimate is outside its interval'
    elif metric in RATIOS and min(values)<=0:reason='Ratio estimates must be positive'
    elif not quote or not all(any(abs(v-n)<1e-8 for n in numerical_tokens(quote)) for v in values):reason='Numerical extraction cannot be traced to the retained passage'
    if reason:return {'eligible':False,'reason':reason,'pmid':effect.get('pmid')}
    value,low,high=values;null=1 if metric in RATIOS else 0
    crossing=low<=null<=high
    interval_kind='credible interval' if re.search(r'credible|\bCrI\b',quote,re.I) else 'confidence interval'
    level_match=re.search(r'(\d+(?:\.\d+)?)\s*%[^.;]{0,35}(?:confidence|credible|\bCI\b|\bCrI\b)',quote,re.I)
    level=float(level_match.group(1)) if level_match else None
    # Absolute units are retained only when attached to the reported estimate.
    unit=None
    if metric=='smd':unit='standard deviations'
    elif metric in RATIOS:unit='ratio'
    else:
        match=re.search(r'(?<![\d.])'+re.escape(str(value).removesuffix('.0'))+r'(?:\.0)?\s*(kg|mg/dL|mmol/L|mmHg|cm|mm|g|points|seconds|minutes|days|months|%)\b',quote,re.I)
        if match:unit=match.group(1)
    interpretation=(f'The reported {interval_kind} includes {null}, the no-difference value. It is compatible with effects on either side of that value; this does not demonstrate equivalence.' if low<null<high else f'The reported {interval_kind} reaches {null}, the no-difference value. This is a boundary result, not evidence of equivalence.') if crossing else f'The reported {interval_kind} lies {"above" if low>null else "below"} {null}, the no-difference value. Whether that change is beneficial or clinically meaningful depends on the endpoint and context.'
    abstract=study.get('abstract') or ''
    normalize=lambda s:' '.join(s.split()).casefold()
    return {'eligible':True,'pmid':str(effect['pmid']),'title':study.get('title'),'year':study.get('year'),'design':study.get('design'),'layer':layer_for(study),'population':study.get('population'),'context_mentions':context_signals(study),'sample_size':study.get('n'),'metric':metric,'measure':MEASURES[metric],'estimate':value,'lower':low,'upper':high,'null':null,'unit':unit,'interval_kind':interval_kind,'interval_level':level,'crosses_null':crossing,'interpretation':interpretation,'comparator':effect.get('comparator') or 'Not extracted','quote':quote,'url':study.get('url') or f'https://pubmed.ncbi.nlm.nih.gov/{effect["pmid"]}/','quote_in_retained_abstract':normalize(quote) in normalize(abstract),'provenance':'Existing verified extraction; original source review remains necessary'}

def analyse_profile(profile):
    outcomes=[];unique={}
    for claim in profile.get('claims',[]):
        studies={study_id(s):s for s in claim.get('studies',[]) if study_id(s)}
        unique.update(studies)
        analysed=[analyse_effect(e,studies) for e in claim.get('effects',{}).get('plottable',[])]
        effects=[];seen=set()
        for effect in analysed:
            if not effect['eligible']:continue
            key=(effect['pmid'],effect['metric'],effect['estimate'],effect['lower'],effect['upper'])
            if key not in seen:effects.append(effect);seen.add(key)
        counts={key:sum(layer_for(s)==key for s in studies.values()) for key in ('mechanism','preclinical','observational','interventional','synthesis','protocol','guidelines','unclassified')}
        missing_n=sum(not finite(s.get('n')) for s in studies.values())
        quantified={e['pmid'] for e in effects}
        flags=[]
        if counts['protocol']:flags.append(f'{counts["protocol"]} protocol record(s) describe planned work, not trial results. Cached grades require review.')
        if counts['synthesis']>1:flags.append('Multiple reviews may include the same trials. Their counts and participants are not independent replication.')
        if any(e['crosses_null'] for e in effects):flags.append('At least one reported interval includes or reaches the no-difference value. Interpret its uncertainty alongside the point estimate.')
        if any(not e['unit'] for e in effects):flags.append('Some absolute estimates have no recoverable units; they are not plotted or compared on a common scale.')
        flags.append('Study-level risk of bias, clinical importance thresholds, and overlap of included populations have not been established by this calculation.')
        if not effects:reading='The retained records do not support a traceable numerical comparison for this outcome. Study volume and an existing grade cannot tell us the size or consistency of benefit.'
        else:reading=f'{len(effects)} reported estimate{"s" if len(effects)!=1 else ""} from {len(quantified)} source{"s" if len(quantified)!=1 else ""} can be inspected. Each estimate is interpreted in its original measure; different endpoints and overlapping reviews are not pooled.'
        outcomes.append({'name':claim['outcome'],'legacy_grade':claim.get('tier'),'grade_status':'refresh_required' if counts['protocol'] else 'existing_automated_appraisal','reading':reading,'counts':counts,'study_count':len(studies),'missing_sample_size':missing_n,'quantified_sources':len(quantified),'effects':effects,'withheld': [e for e in analysed if not e['eligible']],'limitations':flags,'studies':[{'id':key,'title':s.get('title'),'url':s.get('url'),'year':s.get('year'),'design':s.get('design'),'layer':layer_for(s),'population':s.get('population'),'sample_size':s.get('n'),'quantified':key in quantified,'is_preprint':bool(s.get('is_preprint'))} for key,s in studies.items()]})
    quantified_outcomes=sum(bool(o['effects']) for o in outcomes)
    protocols=sum(layer_for(s)=='protocol' for s in unique.values())
    return {'version':VERSION,'name':profile['name'],'generated_at':profile.get('generated_at'),'basis':'Existing cached study records and retained effect passages; no new literature search','outcomes':outcomes,'coverage':{'outcomes':len(outcomes),'quantified_outcomes':quantified_outcomes,'linked_studies':len(unique),'protocols':protocols},'summary':f'{quantified_outcomes} of {len(outcomes)} outcomes have traceable numerical estimates in the retained extractions. '+('Protocol records require an appraisal refresh. ' if protocols else '')+'Evidence volume, effect magnitude, and certainty are assessed separately.','not_computed':['New pooled effects','Total unique participants across reviews','Formal risk-of-bias judgments','Personalized treatment recommendations']}
