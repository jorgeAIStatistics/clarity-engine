"""Bounded cancer-first extraction pass. Every attempt is checkpointed and audited."""
import json,os,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx
from evidence_pipeline.state import State
from evidence_pipeline.extraction.core import SpanProvider
from evidence_pipeline.extraction.service import Extractor
from evidence_pipeline.retrieval.europe_pmc import document_from
from evidence_pipeline.config import Settings
from evidence_pipeline.graph.ingestion import Neo4jIngestor
from evidence_pipeline.common import now
from evidence_pipeline.schemas.pico import SourceDocument
from evidence_pipeline.extraction.observations import ObservationProvider, ObservationExtractor
from . import store, findings
from .intent import alias_present

# Question-specific contexts only; cancer markers use the general cancer filter. Diagnostic and
# prognostic abstracts are handled by the observation schema, not by narrower disease keywords.
SEARCH_CONTEXT={
    'IL-18':'(breast AND (radiotherapy OR radiation) AND pain)',
    'NfL':'(ALS OR "amyotrophic lateral sclerosis")',
}

TOP=['HER2','ER','PR','Ki-67','BRCA1','BRCA2','PD-L1','TMB','MSI','MMR','ctDNA','CA 15-3','CA 27.29','CEA','CA-125','CA19-9','PSA','AFP','β-hCG','Thyroglobulin','Calcitonin','Chromogranin A','LDH','ALP','HE4','EGFR','ALK','KRAS','NRAS','BRAF','IL-18','NfL']

def search_sources(node):
    terms=[a for a in node['aliases'] if len(a)>3][:3] or [node['name']]
    context=SEARCH_CONTEXT.get(node['name'],'(cancer OR carcinoma OR tumor OR neoplasm)')
    query='('+' OR '.join('(TITLE:"'+a.replace('"','')+'" OR ABSTRACT:"'+a.replace('"','')+'")' for a in terms)+') AND '+context+' AND HAS_ABSTRACT:y AND SRC:MED'
    with httpx.Client(timeout=40) as client:
        response=client.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params=dict(query=query,format='json',resultType='core',pageSize=5));response.raise_for_status()
    found=[]
    for record in response.json().get('resultList',{}).get('result',[]):
        identity,source,error=document_from(record)
        if source and any(alias_present(a,source.text) for a in node['aliases']):found.append((identity,source,record))
    return found

def tried_sources(state,node):
    """Abstracts already attempted for this marker, most recent first."""
    order,attempt=[],state.get('biomarker_enrichment',node['id'])
    while attempt:
        if attempt.get('pmid') and attempt['pmid'] not in order:order.append(attempt['pmid'])
        attempt=attempt.get('previous_attempt')
    by_pmid={}
    for candidate in state.all('candidate'):
        if node['id'] in candidate.get('target_ids',[]):
            source=SourceDocument.model_validate_json(json.dumps(candidate['source']))
            by_pmid[source.pmid]=(candidate['study_id'],source,candidate.get('metadata') or {})
    return [by_pmid[p] for p in order if p in by_pmid]

def observations_main(names,attempts=2,search=False):
    registry=json.loads(Path(__file__).with_name('registry.json').read_text())
    settings=Settings.from_env();reports=[]
    for name in names:
        node=next(n for n in registry if n['name']==name)
        state=State(settings.state_path);provider=None
        report=dict(id=node['id'],name=name,mode='observations',at=now().isoformat(),attempts=[],status='no_supported_observations')
        try:
            sources=(search_sources(node) if search else tried_sources(state,node)) or search_sources(node)
            provider=ObservationProvider('anthropic',os.getenv('CLARITY_ENRICH_MODEL','claude-sonnet-5'),os.environ['ANTHROPIC_API_KEY'],max_output_tokens=14000)
            extractor=ObservationExtractor(provider,state,daily_calls=120)
            for identity,source,metadata in sources[:max(1,attempts)]:
                attempt=dict(pmid=source.pmid,study_id=identity)
                try:
                    key,record=extractor.extract(source,run_id='biomarker-observations-pass-v1')
                    record=dict(record,study_id=identity,year=metadata.get('pubYear'),target_ids=[node['id']])
                    state.put('observation_extraction',key,record)
                    with store.session() as session:linked=findings.publish(record,registry,session)
                    attempt.update(status='published',design=record['design']['study_design'],entity_links=linked,findings=[findings.summary(f) for f in record['findings']],excluded=record['excluded'])
                    report['attempts'].append(attempt);report['status']='published';break
                except Exception as error:
                    code=str(error) if re.fullmatch(r'[a-z0-9_]{3,80}',str(error)) else None
                    attempt.update(status='failed',error=type(error).__name__,**({'error_code':code} if code else {}))
                    report['attempts'].append(attempt)
        finally:
            state.put('biomarker_observations',node['id'],report);state.close()
            if provider:provider.close()
            print(json.dumps(report,ensure_ascii=False),flush=True)
        reports.append(report)
    return reports

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Bounded biomarker enrichment')
    parser.add_argument('--observations',nargs='+',metavar='MARKER',help='Extract biomarker observations for these registry names')
    parser.add_argument('--attempts',type=int,default=2,help='Abstracts to try per marker in observation mode')
    parser.add_argument('--search',action='store_true',help='Search new abstracts instead of re-reading tried ones')
    args=parser.parse_args(argv)
    if args.observations:return observations_main(args.observations,args.attempts,args.search)
    nodes=json.loads(Path(__file__).with_name('registry.json').read_text())
    chosen=[next(n for n in nodes if n['name']==name) for name in TOP]
    settings=Settings.from_env()
    def one(node):
        state=State(settings.state_path);provider=None
        prior=state.get('biomarker_enrichment',node['id'])
        if prior and prior.get('status')=='ingested':state.close();return prior
        status=dict(id=node['id'],name=node['name'],at=now().isoformat(),status='searching')
        try:
            terms=[a for a in node['aliases'] if len(a)>3][:3] or [node['name']]
            context=SEARCH_CONTEXT.get(node['name'],'(cancer OR carcinoma OR tumor OR neoplasm)')
            query='('+' OR '.join('(TITLE:"'+a.replace('"','')+'" OR ABSTRACT:"'+a.replace('"','')+'")' for a in terms)+') AND '+context+' AND HAS_ABSTRACT:y AND SRC:MED'
            status['query']=query
            with httpx.Client(timeout=40) as client:
                response=client.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params=dict(query=query,format='json',resultType='core',pageSize=5));response.raise_for_status()
            metadata=response.json();status['hits']=metadata.get('hitCount',0)
            candidates=[]
            for record in metadata.get('resultList',{}).get('result',[]):
                identity,source,error=document_from(record)
                if source and any(alias_present(a,source.text) for a in node['aliases']):candidates.append((record,identity,source))
            if not candidates:status['status']='no_eligible_abstract';return status
            if os.getenv('CLARITY_RETRY_ENRICHMENT') == '1' and prior:
                # Skip every abstract already attempted, not only the most recent one.
                tried,attempt=set(),prior
                while attempt:
                    if attempt.get('pmid'):tried.add(attempt['pmid'])
                    attempt=attempt.get('previous_attempt')
                candidates=[c for c in candidates if c[2].pmid not in tried]
                status['skipped_pmids']=sorted(tried)
                status['previous_attempt']=prior
                if not candidates:status['status']='no_alternative_abstract';return status
            candidates.sort(key=lambda c: len(re.findall(r'(?i)confidence interval|95\s*%|hazard ratio|odds ratio|p\s*[<=>]|sensitivity|specificity',c[2].text)),reverse=True)
            record,identity,source=candidates[0]
            state.put('candidate',identity,dict(id=identity,study_id=identity,source=source.model_dump(mode='json'),metadata=record,target_ids=[node['id']]))
            status['pmid']=source.pmid;status['status']='extracting';state.put('biomarker_enrichment',node['id'],status)
            provider=SpanProvider('anthropic',os.getenv('CLARITY_ENRICH_MODEL','claude-sonnet-5'),os.environ['ANTHROPIC_API_KEY'],max_output_tokens=14000)
            key,envelope=Extractor(provider,state,daily_calls=120).extract([source],run_id='cancer-marker-pass-v1')
            with settings.graph() as graph_driver:
                result=Neo4jIngestor(graph_driver,settings.neo4j_database).ingest(envelope)
            state.put('graph_receipt',key,dict(id=key,at=now().isoformat(),result=result))
            store.link_envelope(key,envelope,nodes)
            status.update(status='ingested',extraction_id=key,results=len(envelope.extraction.results))
            with store.session() as session:
                session.run('MATCH (e:Entity {id:$id}) SET e.last_extracted_at=$at,e.extraction_state="source_validated",e.meaning=$meaning,e.meaning_source_id=$source,e.meaning_source_hash=$hash',id=node['id'],at=now().isoformat(),meaning=next((span.quote for r in envelope.extraction.results for span in r.estimate.evidence),''),source=source.id,hash=source.sha256).consume()
            return status
        except Exception as error:
            # Pipeline errors carry short codes (never source text or credentials); keep them for diagnosis.
            code=str(error) if re.fullmatch(r'[a-z0-9_]{3,80}',str(error)) else None
            status.update(status='extraction_or_search_failed',error=type(error).__name__,**({'error_code':code} if code else {}))
            return status
        finally:
            state.put('biomarker_enrichment',node['id'],status);state.close()
            if provider:provider.close()
            print(json.dumps(status),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,chosen))
    Path('research_state/biomarker-enrichment-report.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
