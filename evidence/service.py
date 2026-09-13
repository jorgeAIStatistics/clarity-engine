"""Versioned evidence catalog and deterministic diagnostic/screening statistics.

None denotes an undefined quantity, never zero or an evidence grade. Reference
summaries do not constitute systematic appraisal. No synthetic study is generated.
"""
import copy
import json
import math
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name('catalog.json').read_text())
ENTITY_TYPES = frozenset(CATALOG['frameworks'])


def probability(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'{name} must be a finite number between 0 and 1')
    return value


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def diagnostic_metrics(sensitivity, specificity, prevalence, population=1000):
    se = probability(sensitivity, 'sensitivity')
    sp = probability(specificity, 'specificity')
    p = probability(prevalence, 'prevalence')
    if isinstance(population, bool) or not isinstance(population, int) or not 1 <= population <= 1000000:
        raise ValueError('population must be an integer from 1 to 1000000')
    tp, fn = population*p*se, population*p*(1-se)
    tn, fp = population*(1-p)*sp, population*(1-p)*(1-sp)
    return dict(true_positive=tp, false_negative=fn, true_negative=tn, false_positive=fp,
                ppv=ratio(tp,tp+fp), npv=ratio(tn,tn+fn), post_negative=ratio(fn,tn+fn),
                lr_positive=ratio(se,1-sp), lr_negative=ratio(1-se,sp),
                diagnostic_odds_ratio=ratio(se*sp,(1-se)*(1-sp)),
                false_positive_rate=1-sp, false_negative_rate=1-se,
                sensitivity=se, specificity=sp, prevalence=p, population=population,
                note='Expected counts, not observed people. Null ratios are undefined or unbounded at the selected boundary.')


def reciprocal_count(risk_difference):
    """Avoid an extra person from binary rounding at an integral reciprocal."""
    reciprocal=1/risk_difference
    if not math.isfinite(reciprocal): return None
    nearest=round(reciprocal)
    return nearest if abs(reciprocal-nearest)<1e-10 else math.ceil(reciprocal)


def screening_metrics(baseline_risk, screened_risk, false_positive_risk=0, procedure_risk=0):
    for name, value in locals().copy().items():
        probability(value, name)
    arr=baseline_risk-screened_risk
    return dict(baseline_events_per_1000=baseline_risk*1000, screened_events_per_1000=screened_risk*1000,
                events_prevented_per_1000=arr*1000, absolute_risk_reduction=arr,
                number_needed_to_screen=reciprocal_count(arr) if arr>0 else None,
                number_needed_to_harm=reciprocal_count(-arr) if arr<0 else None,
                false_positives_per_1000=false_positive_risk*1000, procedures_per_1000=procedure_risk*1000)


def validate_catalog(data):
    ids=[e['id'] for e in data['entities']]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate entity ids')
    for entity in data['entities']:
        typ=entity['entity_type']
        if typ not in ENTITY_TYPES: raise ValueError('Unknown entity type')
        for field in ('evidence_question','population','exposure','comparator','outcomes','studies','sources'):
            if field not in entity: raise ValueError(f'Missing {field}')
        if set(entity['assessments'])!=set(data['frameworks'][typ]['dimensions']): raise ValueError('Wrong assessment framework')
        if not all(r in ids for r in entity['related']): raise ValueError('Unknown relationship')
        if not all(r in data['roles'] for r in entity['roles']): raise ValueError('Unknown biomarker role')
        for source in entity['sources']:
            if not source['url'].startswith('https://'): raise ValueError('Invalid source URL')
        if typ=='precision_oncology' and not entity.get('disease_context'): raise ValueError('Missing oncology context')
    return True


def list_entities(entity_type=None, query='', condition=None):
    if entity_type and entity_type not in ENTITY_TYPES: raise ValueError('Unknown entity_type')
    return [copy.deepcopy(e) for e in CATALOG['entities']
            if (not entity_type or e['entity_type']==entity_type)
            and (not condition or condition.casefold() in [c.casefold() for c in e['conditions']])
            and query.casefold() in ' '.join([e['name'],*e.get('aliases',[]),e['summary'],e['category'],*e['conditions']]).casefold()]


def get_entity(entity_id):
    return next((copy.deepcopy(e) for e in CATALOG['entities'] if e['id']==entity_id),None)


def assessment_framework(entity_type):
    """Dispatch by scientific question; never apply intervention tiers to tests."""
    if entity_type not in ENTITY_TYPES: raise ValueError('Unknown entity_type')
    return copy.deepcopy(CATALOG['frameworks'][entity_type])


validate_catalog(CATALOG)
