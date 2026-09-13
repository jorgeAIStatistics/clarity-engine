"""Evidence-question dispatch and review validation.

The intervention grader is retained. Other domains use independent, source-backed
review dimensions; study counts alone never generate a clinical evidence rating.
"""
from .service import assessment_framework

RATINGS={'Strong','Moderate','Limited','Insufficient','Not yet assessed'}


def grade_entity(entity, reviews=None):
    entity_type=entity.get('entity_type')
    framework=assessment_framework(entity_type)
    if entity_type=='intervention':
        from grade import grade_outcome
        return {'entity_type':entity_type,'method':'existing_intervention_grader',
                'outcomes':{outcome['name']:grade_outcome([study for study in entity.get('studies',[])
                            if study.get('outcome')==outcome['name']]) for outcome in entity.get('outcomes',[])}}
    if reviews is not None and not isinstance(reviews,dict): raise ValueError('reviews must be a dimension-keyed object')
    reviews=reviews or {}
    if set(reviews)-set(framework['dimensions']): raise ValueError('Review dimension does not belong to this entity type')
    source_ids={s.get('id') or s.get('url') for s in entity.get('studies',[])}
    source_ids.update(s.get('url') for s in entity.get('sources',[]))
    result={}
    for dimension in framework['dimensions']:
        review=reviews.get(dimension)
        if review is None:
            result[dimension]={'rating':'Not yet assessed','rationale':'A structured study-level appraisal has not yet been completed.'}
            continue
        if not isinstance(review,dict) or review.get('rating') not in RATINGS: raise ValueError('Invalid review rating')
        if review.get('rating')!='Not yet assessed':
            if not review.get('reviewer') or not review.get('reviewed_at') or not review.get('rationale'):
                raise ValueError('A rating needs a reviewer, date, and rationale')
            if not review.get('source_ids') or not set(review['source_ids']).issubset(source_ids):
                raise ValueError('A rating needs sources present on this entity')
            for field in ('population','outcome','limitations'):
                if not review.get(field): raise ValueError(f'A reviewed assessment needs {field}')
        result[dimension]=dict(review)
    return {'entity_type':entity_type,'method':'independent_review_dimensions','assessments':result,'overall_grade':None}
