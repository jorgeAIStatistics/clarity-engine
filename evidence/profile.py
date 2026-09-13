"""Common presentation contract, preserving domain-specific evidence assessments.

This adapter never regrades evidence or interprets missing metadata as a negative
finding. Generation timestamps are not substituted for search coverage dates.
"""
import re
from .service import assessment_framework

LAYERS=('mechanism','preclinical','observational','interventional','guidelines','synthesis','protocol','unclassified')

def layer_for(study):
    design=str(study.get('design') or study.get('study_type') or '').lower()
    population=str(study.get('population') or '').lower()
    if study.get('is_protocol') or re.search(r'\b(?:study protocol|trial protocol|protocol for (?:a|an|the) .{0,40}trial)\b',str(study.get('title','')).lower()) or 'protocol' in design:return 'protocol'
    if re.search(r'guideline|practice recommendation|regulatory',design):return 'guidelines'
    if re.search(r'animal|mouse|mice|rat\b|preclinical',population) or 'animal' in design:return 'preclinical'
    if re.search(r'in.?vitro|cell|mechanis',population+' '+design):return 'mechanism'
    if re.search(r'meta.analysis|systematic review',design):return 'synthesis'
    if 'human' not in population:return 'unclassified'
    if re.search(r'random|rct|clinical trial|intervention',design):return 'interventional'
    if re.search(r'observ|cohort|case.control|cross.section',design):return 'observational'
    return 'unclassified'

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
