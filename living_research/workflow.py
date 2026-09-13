"""Only an explicit operator review can publish clinical research notes."""
import uuid
from functools import wraps
from .providers import identities
from .engine import now_iso
from .synthesis import build_synthesis


def exclusive(function):
    @wraps(function)
    def call(store,*args,**kwargs):
        owner=str(uuid.uuid4())
        if not store.acquire(owner):raise RuntimeError('Research state is busy; retry after the current run')
        try:return function(store,*args,**kwargs)
        finally:store.release(owner)
    return call


@exclusive
def review(store,proposal_id,reviewer,note,approve):
    proposal=store.get('proposal',proposal_id)
    if not proposal:raise ValueError('Proposal not found')
    if proposal['status'] not in ('review_ready','awaiting_extraction'):raise ValueError('Proposal is not awaiting review')
    if not reviewer.strip() or not note.strip():raise ValueError('Reviewer and review note are required')
    # Metadata-only discoveries may be rejected, but cannot bypass extraction.
    if approve and proposal['status']!='review_ready':raise ValueError('Grounded extraction must be completed before approval')
    proposal.update(status='approved' if approve else 'rejected',review={'reviewer':reviewer,'note':note,'reviewed_at':now_iso()})
    store.put('proposal',proposal_id,proposal)
    return proposal


@exclusive
def publish(store,proposal_id):
    proposal=store.get('proposal',proposal_id)
    if not proposal or proposal['status']!='approved':raise ValueError('Only approved proposals can be published')
    # Lock the publication transaction across both PostgreSQL and SQLite.
    store.execute('BEGIN' if store.pg else 'BEGIN IMMEDIATE')
    try:
        if store.pg:store.execute('SELECT pg_advisory_xact_lock(72193542)')
        # Re-read approval under the publication lock, preventing double publish.
        proposal=store.get('proposal',proposal_id)
        if proposal['status']!='approved':raise ValueError('Proposal is no longer approved')
        if store.get('target',proposal['target_id'],{}).get('scope_hash')!=proposal.get('scope_hash'):raise ValueError('Entity context changed; monitor and extract again before publication')
        current=store.get('published',proposal['target_id'],{'version':0,'updates':[]})
        if current['version']!=proposal['baseline_version']:raise ValueError('Published evidence changed; rebase and review this proposal again')
        aliases=set(identities(proposal['paper']))
        updates=[u for u in current['updates'] if not aliases.intersection(identities(u['paper'])) and u['paper_id']!=proposal['paper_id']]
        updates.append({'proposal_id':proposal_id,'paper_id':proposal['paper_id'],'paper':proposal['paper'],'facts':{k:{**v,'human_verified':True} for k,v in proposal['extraction']['facts'].items()},'summary':proposal.get('proposed_evidence_note',''),'review':proposal['review'],'published_at':now_iso()})
        result={'target_id':proposal['target_id'],'version':current['version']+1,'updates':updates,'updated_at':now_iso(),'clinical_grade_changed':False}
        store.put('published',proposal['target_id'],result)
        proposal['status']='published';store.put('proposal',proposal_id,proposal)
        store.execute('COMMIT');return result
    except Exception:
        store.execute('ROLLBACK');raise


@exclusive
def rebase(store,proposal_id):
    p=store.get('proposal',proposal_id)
    if not p or p['status'] not in ('approved','review_ready'):raise ValueError('Proposal cannot be rebased')
    current=store.get('published',p['target_id'],{'version':0,'updates':[]})
    p.update(baseline_version=current['version'],status='review_ready')
    p.pop('review',None)
    p['synthesis']=build_synthesis(p,current)
    p['diff']['before']=next((u for u in current['updates'] if u['paper_id']==p['paper_id']),None)
    store.put('proposal',proposal_id,p)
    return p
