"""Optional coded feedback. Never persist query text, passages, files or identifiers."""
import base64,hashlib,hmac,json,os,secrets,time,uuid
from .copilot import ANGLES
_SECRET=os.getenv('CLARITY_FEEDBACK_SECRET','').encode() or secrets.token_bytes(32)
CODES={'helpful','not_relevant','missing_angle'}

def token_for(result):
    fields={'id':str(uuid.uuid4()),'expires':int(time.time())+3600,'version':result['version'],
            'targets':[e['id'] for e in result['entities'] if e.get('matched_aliases')][:5]}
    raw=base64.urlsafe_b64encode(json.dumps(fields,separators=(',',':')).encode()).decode().rstrip('=')
    return raw+'.'+hmac.new(_SECRET,raw.encode(),hashlib.sha256).hexdigest()

def record_feedback(store,body):
    if not isinstance(body,dict) or set(body)!={'token','code','angle'}:raise ValueError('Provide a feedback token, code and angle.')
    code=body['code'];angle=body['angle'];token=body['token']
    if not isinstance(code,str) or code not in CODES or not isinstance(angle,str) or angle not in {'',*ANGLES}:raise ValueError('Invalid feedback selection.')
    if code=='missing_angle' and not angle:raise ValueError('Choose the missing research angle.')
    if code!='missing_angle' and angle:raise ValueError('An angle is only needed for missing-angle feedback.')
    try:
        if not isinstance(token,str) or len(token)>3000:raise ValueError()
        raw,signature=token.rsplit('.',1)
        if not hmac.compare_digest(signature,hmac.new(_SECRET,raw.encode(),hashlib.sha256).hexdigest()):raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
        if payload['expires']<time.time():raise ValueError()
    except Exception:raise ValueError('Feedback expired or is invalid. Run matching again to send feedback.') from None
    event={'id':payload['id'],'code':code,'angle':angle,'target_ids':payload['targets'],'version':payload['version'],'created_at':time.time()}
    inserted=store.execute('INSERT INTO clarity_research_records(kind,id,payload,updated) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO NOTHING',('matcher_feedback',payload['id'],json.dumps(event),time.time())).rowcount==1
    return {'status':'recorded' if inserted else 'already_recorded','stored_fields':['code','angle','catalog_target_ids','version','timestamp'],'query_stored':False}

def improvement_signals(store,now=None):
    now=time.time() if now is None else now;cutoff=now-30*86400;signals={}
    rows=store.execute("SELECT payload FROM clarity_research_records WHERE kind='matcher_feedback' AND updated>? ORDER BY updated DESC LIMIT 2000",(cutoff,)).fetchall()
    for row in rows:
        event=json.loads(row['payload'])
        if event.get('code')!='missing_angle':continue
        for target in event.get('target_ids',[]):
            current=signals.setdefault(target,{'missing_angles':set(),'feedback_count':0,'corrections':0})
            current['missing_angles'].add(event['angle']);current['feedback_count']+=1
    # Reviewed rejections identify extraction/appraisal issues, not a clinical verdict.
    for proposal in store.find('proposal',status='rejected',limit=1000):
        from datetime import datetime
        try:recent=datetime.fromisoformat(proposal['review']['reviewed_at'].replace('Z','+00:00')).timestamp()>cutoff
        except (KeyError,ValueError):recent=False
        if recent:
            current=signals.setdefault(proposal['target_id'],{'missing_angles':set(),'feedback_count':0,'corrections':0});current['corrections']+=1
    return {target:{**s,'missing_angles':sorted(s['missing_angles']),'priority_boost':min(8,s['feedback_count']*2)+min(12,s['corrections']*3)} for target,s in signals.items()}

if __name__=='__main__':
    from living_research.store import Store
    store=Store()
    try:
        rows=store.execute("SELECT payload FROM clarity_research_records WHERE kind='matcher_feedback' AND updated>? ORDER BY updated DESC LIMIT 2000",(time.time()-30*86400,)).fetchall()
        from collections import Counter
        print(json.dumps({'window_days':30,'feedback_counts':dict(Counter(json.loads(row['payload'])['code'] for row in rows)),'priority_signals':improvement_signals(store)},indent=2))
    finally:store.close()
