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
        return jsonify({**published,'updates_pending_review':pending,'target_id':target_id,'last_checked':target.get('last_checked'),'last_attempt':target.get('last_attempt'),'monitoring_status':target.get('last_status','not_started')})
    except Exception:
        return jsonify(target_id=target_id,monitoring_status='unavailable',last_checked=None,version=0,updates=[]),503
    finally:
        if store:store.close()
