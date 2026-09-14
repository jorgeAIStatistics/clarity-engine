"""Common presentation contract, preserving domain-specific evidence assessments.

This adapter never regrades evidence or interprets missing metadata as a negative
finding. Generation timestamps are not substituted for search coverage dates.
"""
import json
import re
from pathlib import Path
from .service import assessment_framework

LAYERS=('mechanism','preclinical','observational','interventional','guidelines','synthesis','protocol','unclassified')

# One versioned rule table is shared with clarity-web (python3 -m evidence.export_layers).
LAYER_RULES=json.loads(Path(__file__).with_name('layers.json').read_text())

def _compile(condition):
    return {'flag':condition['flag']} if 'flag' in condition else {'field':condition['field'],'pattern':re.compile(condition['pattern'])}

_RULES=[{'layer':rule['layer'],'any':[_compile(c) for c in rule['any']] if 'any' in rule else None,
         'none':[_compile(c) for c in rule['none']] if 'none' in rule else None} for rule in LAYER_RULES['rules']]

def _field(study,name):
    if name=='population_design':return _field(study,'population')+' '+_field(study,'design')
    value=(study.get('design') or study.get('study_type')) if name=='design' else study.get(name)
    return str(value or '').lower()

def _matches(study,condition):
    if 'flag' in condition:return bool(study.get(condition['flag']))
    return condition['pattern'].search(_field(study,condition['field'])) is not None

def layer_for(study):
    for rule in _RULES:
        hit=any(_matches(study,c) for c in rule['any']) if rule['any'] is not None else not any(_matches(study,c) for c in rule['none'])
        if hit:return rule['layer']
    return LAYER_RULES['default']

def profile_contract(profile,entity_type='intervention'):
    compound=entity_type=='intervention'
    outcomes=profile.get('claims',[]) if compound else profile.get('outcomes',[])
    records=[s for o in outcomes for s in o.get('studies',[])] if compound else profile.get('studies',[])
    unique={}
    for study in records:
        identity=('pmid:'+str(study['pmid'])) if study.get('pmid') else ('doi:'+study['doi'].lower()) if study.get('doi') else study.get('id') or study.get('url')
        if identity and identity not in unique:unique[identity]={**study,'layer':layer_for(study)}
    return {
        'schema_version':'health-profile-v1','entity_type':entity_type,
        'name':profile['name'],'aliases':profile.get('aliases',[]),
        'framework':assessment_framework(entity_type),
        'maturity':('Outcome-dependent' if profile.get('outcome_dependent') else profile.get('best_tier') or profile.get('tier') or 'Not assessed') if compound else profile.get('review_status','reference_summary'),
        'freshness':{'profile_generated_at':profile.get('generated_at'),'sources_checked_through':None,'coverage_note':'Use the living-research completed check; generation time does not establish coverage.'},
        'layers':{layer:{'study_ids':[key for key,s in unique.items() if s['layer']==layer],'coverage':'linked_records_only'} for layer in LAYERS},
        'studies':list(unique.values()),'outcomes':outcomes,
        'assessments':profile.get('assessments'),
        'limitations':['Evidence maturity is outcome- and population-specific.','Missing records do not establish absence of evidence.','Synthesis records can contain overlapping primary studies.'],
        'related':profile.get('related',[]),'sources':profile.get('sources',[]),
        'automatically_regraded':False,
    }
