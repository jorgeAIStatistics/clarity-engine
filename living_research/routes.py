import time
from flask import Blueprint, jsonify
from .store import Store

blueprint=Blueprint('living_research',__name__)

@blueprint.get('/api/living-research/<path:target_id>')
def published_research(target_id):
    if not target_id.startswith(('entity:','compound:')) or len(target_id)>200:return jsonify(error='Invalid target ID'),400
    store=None
    try:
        store=Store()
        target=store.get('target',target_id,{})
        published=store.get('published',target_id,{'version':0,'updates':[]})
        pending=store.pending_count(target_id)
        deferred=store.deferred_count(target_id)
        state=target.get('last_status') or ('queued' if target.get('enabled') else 'not_scheduled')
        return jsonify({**published,'updates_pending_review':pending,'updates_deferred':deferred,'target_id':target_id,'last_checked':target.get('last_checked'),'last_attempt':target.get('last_attempt'),'monitoring_status':state})
    except Exception:
        return jsonify(target_id=target_id,monitoring_status='unavailable',last_checked=None,version=0,updates=[]),503
    finally:
        if store:store.close()

@blueprint.get('/api/living-research/status')
def research_status():
    store=None
    try:
        store=Store()
        worker=store.get('worker','scheduler',{})
        age=time.time()-worker.get('heartbeat',0)
        active=bool(worker) and age<max(900,worker.get('poll_seconds',3600)*2)
        return jsonify(version='layered-synthesis-v1',scheduler='active' if active else 'not_running',
            heartbeat=worker.get('heartbeat'),llm_enabled=worker.get('llm_enabled',False),
            last_run_status=worker.get('last_run_status'),publication_policy='automated_source_validation',
            visual_releases=len(store.all('visual_release')))
    except Exception:
        return jsonify(scheduler='unavailable'),503
    finally:
        if store:store.close()
