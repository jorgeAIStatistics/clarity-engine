from flask import Blueprint, jsonify, request
from .service import CATALOG, list_entities, get_entity, diagnostic_metrics, screening_metrics
from .profile import profile_contract
from functools import lru_cache
import os
import re
import threading
import time

blueprint=Blueprint('evidence',__name__)

# Each map holds a server thread through a Claude parse and graph queries. Extra maps are refused
# at once with a JSON busy response, which keeps CORS headers, instead of failing at the proxy.
MAP_SLOTS=threading.BoundedSemaphore(max(1,min(4,int(os.getenv('CLARITY_MAP_CONCURRENCY','2')))))

def map_busy():
    response=jsonify(error='The evidence map is busy with other questions. Try again in about a minute.',code='busy')
    response.status_code=503;response.headers['Retry-After']='30';response.headers['Cache-Control']='no-store'
    return response

@lru_cache(maxsize=1)
def _visual_snapshot():
    from .visual_report import build_reports
    return build_reports()

@blueprint.get('/api/visual-evidence/<path:target_id>')
def visual_evidence(target_id):
    if not target_id.startswith(('entity:','compound:')) or len(target_id)>160:
        return jsonify(error='Invalid profile'),400
    import copy
    from .visual_report import report, digest, VERSION
    base=copy.deepcopy(_visual_snapshot()['profiles'].get(target_id))
    store=None
    try:
        from living_research.store import Store
        from living_research.automatic import current_releases
        store=Store()
        additions=current_releases(store,target_id)
        if additions and base is None:base=report(target_id,additions[0]['report']['name'],[])
        if base:
            # Observed changes invalidate bundled numeric rows as well as live releases.
            import hashlib, re
            invalid=set()
            for row in base['records']:
                alias=store.get('alias','pmid:'+row['pmid'],{})
                observed=store.get('paper',alias.get('paper_id',''),{}).get('paper',{})
                if observed and (observed.get('corrections') or re.search(r'retract|expression of concern',observed.get('title',''),re.I) or (observed.get('abstract') and hashlib.sha256(observed['abstract'].encode()).hexdigest()!=row['sourceHash'])):
                    invalid.add(row['pmid'])
            rows={r['id']:r for r in base['records'] if r['pmid'] not in invalid}
            if invalid:base.pop('relationship',None)
            studies={s['id']:s for s in base['studies']}
            for item in additions:
                for row in item['report']['records']:rows[row['id']]=row
                for study in item['report']['studies']:studies[study['id']]=study
            base['records']=list(rows.values());base['studies']=list(studies.values())
            base['sourceDate']=max((r.get('extractedAt') or '' for r in base['records']),default=None)
            base.pop('hash',None);base['hash']=digest(base)
    except Exception:
        # A durable selected-source snapshot remains usable during storage outages.
        pass
    finally:
        if store:store.close()
    try:
        from evidence_pipeline.publication import augment_report
        base = augment_report(base, target_id)
    except Exception:
        # Preserve the published snapshot if the independent pipeline is unavailable.
        pass
    response=jsonify(version=VERSION,report=base)
    response.headers['Cache-Control']='private, max-age=60'
    return response

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
        if body.get('workspace'):
            from .intent_graph.service import run
            if not MAP_SLOTS.acquire(blocking=False):return map_busy()
            try:result=run(text)
            finally:MAP_SLOTS.release()
        else:
            result=match(text,library_index(int(time.time()//3600)),study_limit=12)
        from .feedback import token_for
        result['feedback_token']=token_for(result)
        response=jsonify(result);response.headers['Cache-Control']='no-store';return response
    except ValueError as error:return jsonify(error=str(error)),400
    except Exception:return jsonify(error='Library matching is temporarily unavailable. Please try again.'),503

@blueprint.get('/api/evidence/graph/stats')
def graph_stats():
    from .intent_graph.store import graph_stats as stats
    try:data=stats(request.args.get('entity','')[:80])
    except Exception:return jsonify(error='Graph statistics are unavailable.'),503
    response=jsonify(data);response.headers['Cache-Control']='private, max-age=60';return response

@blueprint.get('/api/evidence/graph/entity/<path:entity_id>')
def graph_entity(entity_id):
    if not re.fullmatch(r'[a-z_]+:[a-z0-9-]{1,80}',entity_id):return jsonify(error='Unknown graph profile.'),404
    from .intent_graph.store import graph_entity as load
    try:data=load(entity_id)
    except Exception:return jsonify(error='Graph profiles are unavailable.'),503
    if data is None:return jsonify(error='Unknown graph profile.'),404
    response=jsonify(data);response.headers['Cache-Control']='private, max-age=60';return response

@blueprint.post('/api/evidence/graph/next-step')
def graph_next_step():
    body=request.get_json(silent=True)
    if not isinstance(body,dict):return jsonify(error='Send a next-step object.'),400
    question=str(body.get('question_id') or '')
    if not re.fullmatch(r'question:[0-9a-f]{8,64}',question):return jsonify(error='A stored question id is required.'),400
    payload={k:(str(body.get(k) or '')[:400]) for k in ('title','design','population','outcome','comparator','why','rung')}
    if not payload['title'] or not payload['design']:return jsonify(error='A next step needs a title and a design.'),400
    entities=[e for e in (body.get('entity_ids') or []) if isinstance(e,str) and re.fullmatch(r'[a-z_]+:[a-z0-9-]{1,80}',e)][:8]
    from .intent_graph.store import save_next_step
    try:step=save_next_step(question,{**payload,'entity_ids':entities})
    except Exception:return jsonify(error='The next step could not be stored.'),503
    if not step:return jsonify(error='That question is no longer stored, so a next step cannot be attached to it.'),404
    response=jsonify(stored=True,id=step,expires_in_days=7);response.headers['Cache-Control']='no-store';return response

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

@blueprint.post('/api/research/definition')
def research_definition():
    from .matcher import research_input_error
    from .study_definition import draft
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body)!={'text'} or not isinstance(body['text'],str) or not 5<=len(body['text'].strip())<=12000:
        return jsonify(error='Provide a research abstract, question, PMID or DOI (5–12,000 characters).'),400
    problem=research_input_error(body['text'])
    if problem:return jsonify(error=problem),400
    result=draft(body['text'])
    response=jsonify(result);response.headers['Cache-Control']='no-store';return response
