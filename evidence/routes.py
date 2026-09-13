from flask import Blueprint, jsonify, request
from .service import CATALOG, list_entities, get_entity, diagnostic_metrics, screening_metrics
from .profile import profile_contract
from functools import lru_cache
import time

blueprint=Blueprint('evidence',__name__)

@blueprint.get('/api/library')
def library():
    try:return jsonify(_library_snapshot(int(time.time()//300)))
    except Exception:return jsonify(error='Library unavailable'),503

@lru_cache(maxsize=1)
def _library_snapshot(bucket):
    from .library import build_library
    return build_library()

@blueprint.get('/api/entities')
def entities():
    try:
        items=list_entities(request.args.get('entity_type'),request.args.get('q','')[:200],request.args.get('condition'))
    except ValueError as error:
        return jsonify(error=str(error)),400
    return jsonify(schema_version=CATALOG['schema_version'],catalog_version=CATALOG['catalog_version'],entities=items)

@blueprint.get('/api/entities/<entity_id>')
def entity(entity_id):
    item=get_entity(entity_id)
    return (jsonify({**item,'evidence_profile':profile_contract(item,item['entity_type'])}),200) if item else (jsonify(error='Entity not found'),404)

@blueprint.get('/api/evidence/frameworks')
def frameworks():
    return jsonify(frameworks=CATALOG['frameworks'],roles=CATALOG['roles'],schema_version=CATALOG['schema_version'])


def calculate(function, allowed, required):
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body)-allowed or not required.issubset(body):
        return jsonify(error='Invalid calculation fields'),400
    try:
        return jsonify(function(**body))
    except (ValueError,TypeError) as error:
        return jsonify(error=str(error)),400

@blueprint.post('/api/statistics/diagnostic')
def diagnostic():
    return calculate(diagnostic_metrics,{'sensitivity','specificity','prevalence','population'},{'sensitivity','specificity','prevalence'})

@blueprint.post('/api/statistics/screening')
def screening():
    return calculate(screening_metrics,{'baseline_risk','screened_risk','false_positive_risk','procedure_risk'},{'baseline_risk','screened_risk'})

@blueprint.get('/api/entities/<entity_id>/assessment')
def assessment(entity_id):
    from .appraisal import grade_entity
    item=get_entity(entity_id)
    if item is None: return jsonify(error='Entity not found'),404
    return jsonify(grade_entity(item,item['assessments']))

@blueprint.post('/api/evidence/match')
def evidence_match():
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body) not in ({'text'},{'text','workspace'}) or ('workspace' in body and not isinstance(body['workspace'],bool)):return jsonify(error='Provide a text field and optional workspace boolean.'),400
    from .matcher import match, library_index, research_input_error
    # Validate before any index construction; the bounded query is never logged.
    text=body['text']
    if not isinstance(text,str) or not 20<=len(text.strip())<=12000:return jsonify(error='Enter between 20 and 12,000 characters.'),400
    if research_input_error(text):return jsonify(error=research_input_error(text)),400
    try:
        result=match(text,library_index(int(time.time()//3600)),study_limit=48 if body.get('workspace') else 12)
        from .feedback import token_for
        result['feedback_token']=token_for(result)
        response=jsonify(result);response.headers['Cache-Control']='no-store';return response
    except ValueError as error:return jsonify(error=str(error)),400
    except Exception:return jsonify(error='Library matching is temporarily unavailable. Please try again.'),503

@blueprint.post('/api/evidence/match/feedback')
def matcher_feedback():
    from .feedback import record_feedback
    from living_research.store import Store
    store=None
    try:
        store=Store();response=jsonify(record_feedback(store,request.get_json(silent=True)))
        response.headers['Cache-Control']='no-store';return response
    except ValueError as error:return jsonify(error=str(error)),400
    except Exception:return jsonify(error='Feedback could not be saved. Please try again.'),503
    finally:
        if store:store.close()
