"""Free, conservative queue triage. Scores govern work order, never clinical grades."""
import re

VERSION='metadata-triage-v1'

def classify(paper,target):
    text=' '.join([paper.get('title',''),paper.get('abstract',''),*paper.get('publication_types',[])]).lower()
    types=' '.join(paper.get('publication_types',[])).lower()
    if paper.get('nct_id'):kind='trial_registration'
    elif 'guideline' in types:kind='guideline'
    elif 'meta-analysis' in types or 'systematic review' in types:kind='evidence_synthesis'
    elif 'randomized controlled trial' in types:kind='randomized_trial'
    elif re.search(r'cohort|case.control|observational',types):kind='observational'
    else:kind='unclassified'
    reasons=[];score=0
    if paper.get('corrections') or re.search(r'retract|expression of concern',text):score+=100;reasons.append('Publication integrity requires review')
    if re.search(r'\b(adverse|toxicity|safety|mortality|harm)\b',text):score+=30;reasons.append('Possible safety or mortality content')
    if kind in ('randomized_trial','evidence_synthesis','guideline'):score+=40;reasons.append('Potentially informative study design')
    priority=max(0,min(100,float(target.get('priority',0))))
    score+=priority
    # Query matches establish candidacy, not clinical relevance. Uncertain papers
    # are retained for grounded extraction, rather than automatically discarded.
    return {'version':VERSION,'method':'metadata rules','study_type_candidate':kind,'relevance':'awaiting_grounded_review','impact_score':score,'reasons':reasons,'clinical_impact_established':False,'synthesis_eligible':score>=40,'model_tier':'strong' if score>=40 else 'standard'}
