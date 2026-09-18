"""One catalog of every stored intervention and curated domain profile."""
import json
from datetime import datetime,timezone
from pathlib import Path
import cache
from .service import CATALOG
from .analysis import analyse_profile

PATHS={'biomarker':'biomarkers','diagnostic':'diagnostics','screening':'screening','precision_oncology':'precision-medicine'}

def graph_entries(existing):
    """Biomarkers published to Neo4j that the curated catalog does not already profile."""
    import re
    from collections import Counter
    from .intent_graph.intent import norm
    # A curated profile hides a graph row of the same name. Aliases only hide plain biomarkers:
    # a catalog entry for EGFR-mutant disease must not swallow the EGFR variant entity.
    existing=list(existing)
    known={norm(row['name']) for row in existing}
    known_aliases=known | {norm(a) for row in existing for a in row.get('aliases',[])}
    try:
        from .intent_graph.store import graph_library
        graph=graph_library()
    except Exception:
        # Without this the index silently shrinks to its fourteen curated profiles whenever the
        # graph is unreachable, which reads as "the library is small", not "a read failed".
        from .intent_graph import snapshot
        graph=snapshot.library()
        if not graph:return []
    # Genes and variants share the biomarker address space; a biomarker wins a shared slug.
    kinds={'Biomarker':('Molecular marker',0),'Gene':('Gene',1),'Variant':('Variant',2),'Protein':('Protein',3),
           'Test':('Test',0),'Assay':('Assay',1),'PrecisionContext':('Marker × treatment',0)}
    # Each kind keeps its own index: a test is not a biomarker, and a precision pair is neither.
    routes={'Biomarker':('biomarker','/biomarkers/'),'Gene':('biomarker','/biomarkers/'),'Variant':('biomarker','/biomarkers/'),'Protein':('biomarker','/biomarkers/'),
            'Test':('diagnostic','/diagnostics/'),'Assay':('diagnostic','/diagnostics/'),'PrecisionContext':('precision_oncology','/precision-medicine/')}
    rows,by_slug={},{}
    for g in graph:
        kind=g.get('kind') or {'biomarker':'Biomarker','gene':'Gene','variant':'Variant','protein':'Protein','test':'Test','assay':'Assay','precision_context':'PrecisionContext'}.get(g.get('type'),'')
        if kind not in kinds:continue
        category,rank=kinds[kind]
        hidden=known_aliases if kind=='Biomarker' else known
        if any(norm(name) in hidden for name in [g['name'],*(g.get('aliases') or [])] if kind=='Biomarker' or name==g['name']):continue
        slug=g['id'].split(':',1)[1]
        if not re.fullmatch(r'[a-z0-9-]{1,80}',slug):continue
        entity_type,prefix=routes[kind]
        # A screening test answers a different question from a diagnostic one; keep the two indexes apart.
        if entity_type=='diagnostic' and any('screening' in str(name).lower() for name in [g['name'],*(g.get('aliases') or [])]):
            entity_type,prefix='screening','/screening/'
        # A gene and the protein it encodes share a name, and the protein wins the plain address.
        # The gene used to be dropped outright, so seven genes carrying HGNC, Ensembl, UniProt and a
        # locus had no page at all and the protein's "encoded by" link pointed back at itself.
        # The loser takes a suffixed address instead, so both objects exist.
        if slug in by_slug and by_slug[slug]<=rank:
            suffix={'Gene':'-gene','Variant':'-variant','Protein':'-protein'}.get(kind)
            if not suffix or slug+suffix in by_slug:continue
            slug=slug+suffix
        by_slug[slug]=rank
        sentences=[s for layer in g.get('sentences') or [] for s in (json.loads(layer) if layer else []) if not s.startswith('No indexed')]
        summary=sentences[0] if sentences else f"{g['name']}: aliases and five evidence layers are indexed in the graph; no typed findings are extracted yet."
        rows[slug]={'id':'graph:'+g['id'],'name':g['name'],'entity_type':entity_type,'category':category,'aliases':g.get('aliases') or [],'path':prefix+slug,
            'outcomes':[],'conditions':[],'review_status':'automated_appraisal','available':True,'generated_at':None,'last_enriched_at':(g.get('last_extracted_at') or '')[:10] or None,
            'summary':summary,'coverage':{'linked_studies':g.get('studies',0),'outcomes':0,'quantified_outcomes':g.get('findings',0)},'maturity':'Graph profile · automated',
            'quantified_outcome_names':[],'graph_layers':g.get('layers',[]),
            'finding_kinds':{k:v for k,v in sorted(Counter(k for k in (g.get('kinds') or []) if k).items())},
            'utility_indexed':bool(g.get('utility_findings')),'trial_findings':g.get('trial_findings') or 0}
    return list(rows.values())

def build_library():
    import generate
    from .enrichment import OVERLAYS
    entries={};audit=[]
    for key,p in cache.iter_profiles():
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
    graph=graph_entries(entries.values())
    for row in graph:entries[row['id']]=row
    rows=sorted(entries.values(),key=lambda r:r['name'].casefold())
    return {'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'coverage_statement':'Complete inventory of stored Clarity profiles; not an exhaustive catalog of medicine or a completed systematic review.','entries':rows,'counts':{typ:sum(e['entity_type']==typ for e in rows) for typ in ['intervention',*PATHS]},'graph_rows':len(graph),'audit':audit}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    result=build_library();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps({'entries':len(result['entries']),'counts':result['counts'],'withheld_estimates':sum(r['withheld_estimates'] for r in result['audit'])}))
