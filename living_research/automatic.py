"""Automatic publication of narrowly supported reported estimates.

This does not publish LLM conclusions or clinical grades. The existing operator
workflow remains available for legacy notes, but is not on this release path.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from evidence.visual_report import release, report, digest

NUM = r'(?:\d*\.\d+|\d+)'
PATTERN = re.compile(r'(?P<endpoint>[A-Za-z][A-Za-z ,\-/]{3,90}?)\s*\('
    r'(?P<measure>hazard ratio|odds ratio|risk ratio|rate ratio)[,;:= ]+'
    r'(?P<point>'+NUM+r')[,; ]+(?P<level>'+NUM+r')%\s*'
    r'(?:confidence interval\s*(?:\[CI\])?|CI)[,;:=\[ ]*'
    r'(?P<lower>'+NUM+r')\s*(?:to|[–−-])\s*(?P<upper>'+NUM+r')', re.I)

def source_span(text, quote, pmid):
    start=text.index(quote)
    return {'text':quote,'start':start,'end':start+len(quote),'source_id':'pmid:'+pmid,'basis':'normalized abstract'}

def extract_reported_study(paper, target):
    text=paper.get('abstract') or ''
    pmid=str(paper.get('pmid') or '')
    if not pmid.isdigit() or paper.get('is_preprint') or paper.get('corrections'):return None
    if re.search(r'retract|expression of concern|protocol', paper.get('title',''), re.I):return None
    # A named entity must occur as a complete token; relevance-model prose is not
    # sufficient to publish a record. Missing aliases simply yield no release.
    terms=[target.get('name',''),*target.get('aliases',[])]
    matches_term=lambda t: len(t)>=3 and re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',text,re.I)
    groups=target.get('term_groups',[])
    if not any(matches_term(t) for t in terms) and not (groups and all(any(matches_term(t) for t in group) for group in groups)):return None
    matches=list(PATTERN.finditer(text))
    if not matches:return None
    sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',text)
    population=next((s for s in sentences if re.search(r'participants|patients|adults|women|men ',s,re.I)),None)
    comparison=next((s for s in sentences if re.search(r'versus|compared with|placebo',s,re.I)),None)
    if not population or not comparison:return None
    comparison_terms=[*terms,*(groups[0] if groups else [])]
    if not any(len(t)>=3 and re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',comparison,re.I) for t in comparison_terms):return None
    findings=[]
    for m in matches:
        quote=m.group(0); endpoint=m['endpoint'].strip(' ,')
        if len(endpoint)<4:continue
        findings.append({'outcome':endpoint,'effect':{'measure':m['measure'].lower(),'estimate':float(m['point']),
            'lower':float(m['lower']),'upper':float(m['upper']),'confidence_level':float(m['level']),
            'units':'reported contrast','origin':'reported'},'quote':quote,'source_span':source_span(text,quote,pmid)})
    if not findings:return None
    trial=re.search(r'\bNCT\d{8}\b',text)
    return {'pmid':pmid,'id':'pmid:'+pmid,'title':paper.get('title'),'doi':paper.get('doi'),
        'url':f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/','abstract':text,'year':str(paper.get('year') or paper.get('publication_date','')[:4]),
        'design':'Randomized controlled trial' if re.search(r'randomi[sz]ed',text,re.I) else 'Observational study' if re.search(r'cohort|observational',text,re.I) else 'Source-defined study',
        'population':population,'exposure':comparison,'comparator':comparison,
        'population_span':source_span(text,population,pmid),'scope_passage':source_span(text,comparison,pmid),
        'cohort_id':trial.group(0) if trial else None,'findings':findings,
        'extraction':{'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'extracted_at':datetime.now(timezone.utc).isoformat(),'version':'literal-ratio-parser-v1'}}

def auto_publish(store, proposal):
    study=extract_reported_study(proposal['paper'],proposal['target'])
    if not study:return False
    result=report(proposal['target_id'],proposal['target']['name'],[study])
    if not result['records']:return False
    current=store.get('visual_release',proposal['id'])
    if current:return False
    item={'id':proposal['id'],'target_id':proposal['target_id'],'paper_id':proposal['paper_id'],
        'fingerprint':proposal['fingerprint'],'scope_hash':proposal['scope_hash'],
        'report':result,'published_at':datetime.now(timezone.utc).isoformat(),'policy':'automated_source_validation'}
    # One complete immutable record is the atomic public unit. No partial rows.
    store.put('visual_release',proposal['id'],item)
    store.put('audit','visual:'+proposal['id'],{'action':'automatic_visual_publication','target_id':proposal['target_id'],
        'proposal_id':proposal['id'],'hash':result['hash'],'at':item['published_at'],'clinical_grade_changed':False})
    return True

def current_releases(store,target_id):
    target=store.get('target',target_id,{})
    result=[]
    for item in store.find('visual_release',target_id=target_id):
        paper=store.get('paper',item['paper_id'],{})
        source=paper.get('paper',paper)
        if paper.get('fingerprint')==item['fingerprint'] and target.get('scope_hash')==item['scope_hash'] and not source.get('corrections') and not re.search(r'retract|expression of concern',source.get('title',''),re.I):
            result.append(item)
    return result


def reconcile(store, limit=100):
    """Bounded, resumable free extraction of the retained proposal backlog."""
    proposals=[json.loads(row['payload']) for row in store.execute("SELECT p.payload FROM clarity_research_records p WHERE p.kind='proposal' AND NOT EXISTS (SELECT 1 FROM clarity_research_records a WHERE a.kind='visual_attempt' AND a.id=p.id) ORDER BY p.updated ASC LIMIT ?",(min(max(int(limit),1),250),)).fetchall()]
    published=0
    for proposal in proposals:
        if store.get('visual_attempt',proposal['id']):continue
        published += bool(auto_publish(store,proposal))
        store.put('visual_attempt',proposal['id'],{'version':'literal-ratio-parser-v1','target_id':proposal['target_id']})
    return published
