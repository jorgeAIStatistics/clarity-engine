"""Idempotent registry + retained source migration. No new scientific claims."""
import json,hashlib,re
from pathlib import Path
from . import store
from .intent import alias_present

def main():
    from evidence.matcher import documents
    from evidence.service import CATALOG
    from evidence.visual_report import build_reports
    from evidence_pipeline.publication import current_records,visual_rows
    nodes=json.loads(Path(__file__).with_name('registry.json').read_text())
    store.seed(nodes)
    _,records=documents(CATALOG['entities'])
    by_id={r['id']:r for r in records}
    from evidence_pipeline.state import State
    from evidence_pipeline.config import Settings
    from evidence_pipeline.schemas.pico import SourceDocument
    from evidence.profile import layer_for
    from evidence.copilot import record_angles
    state=State(Settings.from_env().state_path)
    observations=[]
    try:
        observations=state.all('observation_extraction')
        for candidate in state.all('candidate'):
            if candidate['study_id'] in by_id:continue
            if not any(t.startswith('biomarker:') for t in candidate.get('target_ids',[])):continue
            source=SourceDocument.model_validate_json(json.dumps(candidate['source']))
            metadata=candidate.get('metadata',{})
            design=' '.join(metadata.get('pubTypeList',{}).get('pubType',[]))
            # Explicit design phrases are retained as source evidence; generic
            # journal article metadata alone does not classify an evidence layer.
            pattern=r'(?i)prospective cohort|retrospective cohort|cross-sectional|case-control|randomized controlled trial|randomised controlled trial|meta-analysis|systematic review'
            phrase=re.search(pattern,source.text)
            if phrase:design=phrase.group()
            doc=dict(id=candidate['study_id'],pmid=source.pmid,title=metadata.get('title') or source.text.split('\n')[0],url=source.source_url,year=metadata.get('pubYear'),design=design,population=None,n=None,
                layer=layer_for({'design':design}),findings=[],exposure=None,comparator=None,cohort_id=None,entity_ids=[],_passages=[],_text=source.text,agreement='not_assessed',review_status='automated',layer_passage=phrase.group() if phrase else None)
            doc['angles']=record_angles(doc);records.append(doc);by_id[doc['id']]=doc
    finally:state.close()
    visual=[r for p in build_reports()['profiles'].values() for r in p['records']]
    for item in current_records():
        visual.extend(visual_rows(item)[0]);store.link_envelope(item['id'],item['envelope'],nodes)
    for r in visual:
        doc=by_id.get('pmid:'+r['pmid'])
        if not doc:continue
        finding=dict(plot_eligible=True,outcome=r['outcome'],quote=r['quote'],entity_ids=[],population=r['context'].get('population'),exposure=r['context'].get('exposure'),comparator=r['context'].get('comparator'),timepoint=r['context'].get('timepoint') or r['context'].get('duration'),effect=dict(measure=r['metric'],estimate=r['point'],lower=r['lower'],upper=r['upper'],confidence_level=r['intervalLevel'],units=r.get('unit'),origin='reported'))
        # Existing source text must contain the figure's exact quote.
        if r['quote'] in doc['_text'] and finding not in doc['findings']:doc['findings'].append(finding)
    from .findings import apply_observations,matcher_document,publish
    for record in observations:
        doc=by_id.get(record['study_id'])
        if doc:apply_observations(doc,record)
        else:
            doc=matcher_document(record);records.append(doc);by_id[doc['id']]=doc
    total=0
    with store.session() as s:
        for record in records:
            source=record.get('title','')+' '+record.get('_text','')
            hits=[n for n in nodes if any(alias_present(a,source) for a in n['aliases'])]
            if not hits:continue
            record={k:v for k,v in record.items() if k!='_tokens'}
            record['findings']=[{**f,'plot_eligible':f.get('plot_eligible',False)} for f in record.get('findings',[]) if f.get('quote') and f['quote'] in record.get('_text','')]
            payload=json.dumps(record,ensure_ascii=False)
            s.run('MERGE (s:Study {id:$id}) MERGE (r:MatcherRecord {id:$record}) SET r.payload_json=$payload,r.source_hash=$hash,r.source_text=$text,r.review_state="automated" MERGE (s)-[:HAS_MATCHER_RECORD]->(r)',id=record['id'],record='matcher:'+record['id'],payload=payload,text=record.get('_text',''),hash=hashlib.sha256(record.get('_text','').encode()).hexdigest()).consume()
            for n in hits:
                s.run('MATCH (s:Study {id:$study}),(e:Entity {id:$entity}) MERGE (s)-[r:MENTIONS_ENTITY]->(e) SET r.review_state="automated",r.method="exact_alias_in_source"',study=record['id'],entity=n['id']).consume()
                if record.get('layer') in store.LAYERS:
                    s.run('MATCH (e:Entity {id:$entity})-[:HAS_LAYER]->(l:LayerAssessment {layer:$layer}) SET l.status="INDEXED",l.review_state="automated"',entity=n['id'],layer=record['layer']).consume()
            total+=1
        for record in observations:publish(record,nodes,s)
    print(json.dumps({'biomarkers':sum(n['type']=='biomarker' for n in nodes),'source_records':total,'observation_records':len(observations)}))
if __name__=='__main__':main()
