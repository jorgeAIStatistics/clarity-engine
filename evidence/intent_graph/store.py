"""Neo4j is the matcher source of truth. No disease-neighbor traversal."""
import hashlib
from functools import lru_cache
from datetime import datetime,timezone,timedelta
from evidence_pipeline.config import Settings
from evidence_pipeline.schemas.pico import ExtractionEnvelope
from .intent import resolve_alias,complete_entities

LAYERS=('mechanism','preclinical','observational','interventional','guidelines')
@lru_cache(maxsize=1)
def driver():return Settings.from_env().graph()

def session():return driver().session(database=Settings.from_env().neo4j_database)

def seed(nodes):
    with session() as s:
        s.run('CREATE CONSTRAINT clarity_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE').consume()
        s.run('CREATE CONSTRAINT clarity_layer_id IF NOT EXISTS FOR (l:LayerAssessment) REQUIRE l.id IS UNIQUE').consume()
        for n in nodes:
            s.run('MERGE (e:Entity {id:$id}) SET e.name=$name,e.aliases=$aliases,e.type=$type,e.review_state="automated",e.ephemeral=false,e.registry_version=$version',id=n['id'],name=n['name'],aliases=n['aliases'],type=n['type'],version=n['registry_version']).consume()
            if n['type']=='biomarker':s.run('MATCH (e:Entity {id:$id}) SET e:Biomarker',id=n['id']).consume()
            for layer in LAYERS:
                s.run('MATCH (e:Entity {id:$entity}) MERGE (l:LayerAssessment {id:$id}) ON CREATE SET l.layer=$layer,l.status="GAP",l.review_state="automated" MERGE (e)-[:HAS_LAYER]->(l)',entity=n['id'],id=n['id']+':'+layer,layer=layer).consume()

def resolve(intent,text):
    with session() as s:
        s.run('MATCH (e:Entity {ephemeral:true}) WHERE e.expires_at < $now OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment) DETACH DELETE e,l',now=datetime.now(timezone.utc).isoformat()).consume()
        nodes=[dict(r['e']) for r in s.run('MATCH (e:Entity) WHERE e.ephemeral=false RETURN e')]
        intent.entities=complete_entities(intent,text,nodes).entities
        resolved=[]
        for entity in intent.entities:
            node=resolve_alias(entity,nodes)
            if node is None:
                # Store only the entity span, never the researcher's full question or table.
                identifier='temporary:'+hashlib.sha256((entity.type+'|'+entity.question_span.casefold()).encode()).hexdigest()[:24]
                node=dict(id=identifier,name=entity.question_span,aliases=[entity.question_span],type=entity.type,ephemeral=True)
                s.run('MERGE (e:Entity {id:$id}) SET e.name=$name,e.aliases=$aliases,e.type=$type,e.ephemeral=true,e.review_state="automated",e.expires_at=$expiry',**node,expiry=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()).consume()
                for layer in LAYERS:
                    s.run('MATCH (e:Entity {id:$entity}) MERGE (l:LayerAssessment {id:$id}) ON CREATE SET l.layer=$layer,l.status="GAP",l.review_state="automated" MERGE (e)-[:HAS_LAYER]->(l)',entity=identifier,id=identifier+':'+layer,layer=layer).consume()
            if node['id'] not in {n['id'] for n in resolved}:resolved.append(node)
        return resolved

def artifacts(entity_ids):
    with session() as s:
        # Only explicitly linked records, not any sibling in a shared disease.
        data=s.run('MATCH (e:Entity)<-[:MENTIONS_ENTITY]-(s:Study)-[:HAS_EXTRACTION]->(x:Extraction) WHERE e.id IN $ids RETURN DISTINCT x.id AS id,x.payload_json AS payload LIMIT 1500',ids=entity_ids).data()
    return [(r['id'],ExtractionEnvelope.model_validate_json(r['payload'])) for r in data]

def link_envelope(extraction_id,envelope,nodes):
    from .intent import alias_present
    # A MENTIONS_ENTITY edge is lexical provenance, never IMPROVES/PREDICTS.
    source=envelope.sources[0]
    hits=[n for n in nodes if any(alias_present(a,source.text) for a in n['aliases'])]
    with session() as s:
        for n in hits:
            s.run('MATCH (s:Study)-[:HAS_EXTRACTION]->(x:Extraction {id:$extraction}), (e:Entity {id:$entity}) MERGE (s)-[r:MENTIONS_ENTITY]->(e) SET r.method="exact_alias_in_source",r.source_hash=$hash,r.review_state="automated"',extraction=extraction_id,entity=n['id'],hash=source.sha256).consume()
    return len(hits)


def graph_stats(entity_id=''):
    """Aggregate counts from the graph this process reads. No credentials or question text."""
    import re
    with session() as s:
        one=lambda query,**kw: s.run(query,**kw).single()[0]
        data=dict(version='graph-stats-v1',
            entities=one('MATCH (e:Entity) WHERE e.ephemeral=false RETURN count(e)'),
            biomarkers=one('MATCH (e:Entity:Biomarker) WHERE e.ephemeral=false RETURN count(e)'),
            biomarkers_with_aliases=one('MATCH (e:Entity:Biomarker) WHERE e.ephemeral=false AND size(e.aliases)>=2 RETURN count(e)'),
            temporary_entities=one('MATCH (e:Entity {ephemeral:true}) RETURN count(e)'),
            studies=one('MATCH (s:Study) RETURN count(s)'),
            matcher_records=one('MATCH (r:MatcherRecord) RETURN count(r)'),
            entity_links=one('MATCH ()-[m:MENTIONS_ENTITY]->() RETURN count(m)'),
            findings=one('MATCH (f:Finding) RETURN count(f)'),
            findings_by_type={r['type']:r['n'] for r in s.run('MATCH (f:Finding) RETURN f.observation_type AS type,count(f) AS n ORDER BY type')})
        if re.fullmatch(r'[a-z_]+:[a-z0-9-]{1,60}',entity_id or ''):
            row=s.run('MATCH (e:Entity {id:$id}) OPTIONAL MATCH (e)<-[:ABOUT]-(f:Finding) WITH e,collect(f{.observation_type,.measure,.value_raw,.threshold,.lower,.upper,.passage,.source_id}) AS found OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(st:Study) RETURN e.name AS name,e.aliases AS aliases,e.meaning_type AS meaning_type,found,count(DISTINCT st) AS studies',id=entity_id).single()
            data['entity']=dict(id=entity_id,name=row['name'],aliases=row['aliases'],studies=row['studies'],meaning_type=row['meaning_type'],findings=row['found']) if row else None
    return data
