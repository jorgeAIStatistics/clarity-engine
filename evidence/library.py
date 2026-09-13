"""One catalog of every stored intervention and curated domain profile."""
import json
from datetime import datetime,timezone
from pathlib import Path
import cache
from .service import CATALOG
from .analysis import analyse_profile

PATHS={'biomarker':'biomarkers','diagnostic':'diagnostics','screening':'screening','precision_oncology':'precision-medicine'}

def build_library():
    import generate
    from .enrichment import OVERLAYS
    entries={};audit=[]
    for key in cache.list_cached():
        p=cache.get(key,max_age_days=100000)
        if not isinstance(p,dict) or not p.get('name') or not p.get('claims'):continue
        slug=cache._slug(p['name'])
        analysis=analyse_profile(p)
        current=p.get('engine_version')==generate.ENGINE_VERSION and int(p.get('schema_version') or 0)>=generate.PROFILE_SCHEMA_VERSION
        row={'id':'compound:'+slug,'name':p['name'],'entity_type':'intervention','category':p.get('category') or 'intervention','aliases':p.get('aliases',[]),'path':'/compound/'+slug,'outcomes':[c['outcome'] for c in p['claims']],'conditions':[],'review_status':'refresh_required' if analysis['coverage']['protocols'] or not current else 'automated_appraisal','available':current,'generated_at':p.get('generated_at'),'summary':analysis['summary'],'coverage':analysis['coverage'],'maturity':p.get('display_tier') or p.get('tier'),'analysis_version':analysis['version'],'quantified_outcome_names':[o['name'] for o in analysis['outcomes'] if o['effects']]}
        selected=OVERLAYS['profiles'].get(slug)
        if selected:
            records=[s for claim in p['claims'] for s in claim.get('studies',[])]+selected['studies']
            identities={str(s.get('pmid') or s.get('doi') or s.get('id') or s.get('url')) for s in records if s.get('pmid') or s.get('doi') or s.get('id') or s.get('url')}
            names=list(dict.fromkeys(row['quantified_outcome_names']+[f['outcome'] for s in selected['studies'] for f in s.get('findings',[])]))
            row['coverage']={**row['coverage'],'linked_studies':len(identities),'quantified_outcomes':len(names),'selected_publications':len(selected['studies'])}
            row['quantified_outcome_names']=names;row['last_enriched_at']='2026-09-13'
        old=entries.get(row['id'])
        if not old or str(row['generated_at'] or '')>str(old['generated_at'] or ''):entries[row['id']]=row
        audit.append({'id':row['id'],'withheld_estimates':sum(len(o['withheld']) for o in analysis['outcomes']),'protocols':analysis['coverage']['protocols']})
    for e in CATALOG['entities']:
        row={'id':'entity:'+e['id'],'name':e['name'],'entity_type':e['entity_type'],'category':e['category'],'aliases':e.get('aliases',[]),'path':f'/{PATHS[e["entity_type"]]}/{e["id"]}','outcomes':[o['name'] for o in e['outcomes']],'conditions':e.get('conditions',[]),'review_status':e['review_status'],'available':True,'generated_at':None,'last_enriched_at':e.get('last_enriched_at'),'summary':e['summary'],'coverage':{'linked_studies':len({s.get('pmid') or s.get('id') or s.get('url') for s in e['studies']}),'outcomes':len(e['outcomes']),'quantified_outcomes':len({f['outcome'] for s in e['studies'] for f in (s.get('findings') or ([s] if s.get('effect') else [])) if f.get('effect')})},'maturity':'Human evidence indexed' if e['studies'] and e['review_status']!='reviewed' else 'Appraisal incomplete' if e['review_status']!='reviewed' else 'Reviewed by dimension'}
        row['quantified_outcome_names']=list(dict.fromkeys(f['outcome'] for s in e['studies'] for f in (s.get('findings') or ([s] if s.get('effect') else [])) if f.get('effect')))
        entries[row['id']]=row
    rows=sorted(entries.values(),key=lambda r:r['name'].casefold())
    return {'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'coverage_statement':'Complete inventory of stored Clarity profiles; not an exhaustive catalog of medicine or a completed systematic review.','entries':rows,'counts':{typ:sum(e['entity_type']==typ for e in rows) for typ in ['intervention',*PATHS]},'audit':audit}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    result=build_library();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps({'entries':len(result['entries']),'counts':result['counts'],'withheld_estimates':sum(r['withheld_estimates'] for r in result['audit'])}))
