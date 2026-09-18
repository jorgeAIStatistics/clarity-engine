"""Neo4j is the matcher source of truth. No disease-neighbor traversal."""
import hashlib
import json
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from evidence_pipeline.config import Settings
from evidence_pipeline.schemas.pico import ExtractionEnvelope
from .intent import resolve_alias, complete_entities, compatible, norm
from . import cypher

LAYERS = cypher.LAYERS
REGISTRY_PREFIX = 'biomarkers-'
CONSTRAINTS = (
    'CREATE CONSTRAINT clarity_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE',
    'CREATE CONSTRAINT clarity_layer_id IF NOT EXISTS FOR (l:LayerAssessment) REQUIRE l.id IS UNIQUE',
    'CREATE CONSTRAINT clarity_alias_id IF NOT EXISTS FOR (a:EntityAlias) REQUIRE a.id IS UNIQUE',
    'CREATE INDEX clarity_alias_norm IF NOT EXISTS FOR (a:EntityAlias) ON (a.norm_name)',
    'CREATE CONSTRAINT clarity_finding_id IF NOT EXISTS FOR (f:Finding) REQUIRE f.id IS UNIQUE',
    'CREATE CONSTRAINT clarity_question_id IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE',
)


@lru_cache(maxsize=1)
def driver():
    return Settings.from_env().graph()


def session():
    return driver().session(database=Settings.from_env().neo4j_database)


def seed(nodes, version='biomarkers-v2'):
    ids = sorted({n['id'] for n in nodes})
    with session() as s:
        for query in CONSTRAINTS:
            s.run(query).consume()
        # Automated registry entities the current registry no longer names (e.g. BRCA1 moved to a gene id) are retired.
        retired = "MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false AND e.registry_version STARTS WITH $prefix AND NOT e.id IN $ids AND coalesce(e.review_state,'automated')<>'reviewed'"
        s.run(retired + ' OPTIONAL MATCH (e)-[:HAS_LAYER|HAS_ALIAS]->(x) DETACH DELETE x', prefix=REGISTRY_PREFIX, ids=ids).consume()
        s.run(retired + ' DETACH DELETE e', prefix=REGISTRY_PREFIX, ids=ids).consume()
        for n in nodes:
            # Aliases are rebuilt from the registry so a removed alias stops resolving.
            s.run("MATCH (e:Entity {id:$id})-[:HAS_ALIAS]->(a:EntityAlias) WHERE coalesce(a.source,'registry')='registry' DETACH DELETE a", id=n['id']).consume()
            cypher.run_all(s, cypher.entity_statements(n, version))
        for n in nodes:
            cypher.run_all(s, cypher.relation_statements(n, set(ids)))


def resolve(intent, text, store_question_text=False):
    """Question spans → Entity nodes via EntityAlias, temporary nodes on a miss, and Question MENTIONS edges."""
    with session() as s:
        s.run('MATCH (e:Entity {ephemeral:true}) WHERE e.expires_at < $now OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment) DETACH DELETE e,l', now=datetime.now(timezone.utc).isoformat()).consume()
        # A suggested design lives exactly as long as the question that prompted it.
        s.run('MATCH (n:NextStep) WHERE n.expires_at < $now DETACH DELETE n', now=datetime.now(timezone.utc).isoformat()).consume()
        nodes = [dict(r['e']) for r in s.run('MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false RETURN e')]
        intent.entities = complete_entities(intent, text, nodes).entities
        resolved = []
        for entity in intent.entities:
            candidates = [dict(r['e']) for r in s.run(cypher.RESOLVE_SPAN, norm=norm(entity.question_span))]
            candidates = [c for c in candidates if compatible(entity.type, c['type'])]
            node = candidates[0] if len(candidates) == 1 else resolve_alias(entity, nodes)
            if node is None:
                # Store only the entity span, never the researcher's full question or table.
                identifier = 'temporary:' + hashlib.sha256((entity.type + '|' + entity.question_span.casefold()).encode()).hexdigest()[:24]
                node = dict(id=identifier, name=entity.question_span, aliases=[entity.question_span], type=entity.type, ephemeral=True)
                s.run('MERGE (e:Entity {id:$id}) SET e.name=$name, e.aliases=$aliases, e.type=$type, e.kind=$kind, e.ephemeral=true, e.review_state="automated", e.expires_at=$expiry',
                      id=identifier, name=node['name'], aliases=node['aliases'], type=node['type'], kind=cypher.KIND.get(node['type'], 'Biomarker'), expiry=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat()).consume()
                for layer in LAYERS:
                    s.run("MATCH (e:Entity {id:$entity}) MERGE (l:LayerAssessment {id:$id}) ON CREATE SET l.layer=$layer, l.status='GAP', l.n_findings=0, l.review_state='automated' MERGE (e)-[:HAS_LAYER]->(l)",
                          entity=identifier, id=identifier + ':' + layer, layer=layer).consume()
            if node['id'] not in {n['id'] for n in resolved}:
                resolved.append(node)
        qid, statements = cypher.question_statements(text, intent.model_dump(), [n['id'] for n in resolved], store_text=store_question_text)
        cypher.run_all(s, statements)
        return resolved, qid


def save_next_step(question_id, payload):
    """Store a suggested study design against its question. Refused when the question has expired."""
    with session() as s:
        if not s.run('MATCH (q:Question {id:$id}) RETURN q.id AS id', id=question_id).single():
            return None
        step_id, statements = cypher.next_step_statements(question_id, payload)
        cypher.run_all(s, statements)
        return step_id


def question_payload(qid):
    """Heatmap layer rollups and cell findings for one question, from its MENTIONS subgraph only."""
    with session() as s:
        return s.run(cypher.COVERAGE_PAYLOAD, qid=qid).data(), s.run(cypher.CELL_FINDINGS, qid=qid).data()


def artifacts(entity_ids):
    with session() as s:
        # Only explicitly linked records, not any sibling in a shared disease.
        data = s.run('MATCH (e:Entity)<-[:MENTIONS_ENTITY]-(s:Study)-[:HAS_EXTRACTION]->(x:Extraction) WHERE e.id IN $ids RETURN DISTINCT x.id AS id,x.payload_json AS payload LIMIT 1500', ids=entity_ids).data()
    return [(r['id'], ExtractionEnvelope.model_validate_json(r['payload'])) for r in data]


def link_envelope(extraction_id, envelope, nodes):
    from .intent import alias_present
    # A MENTIONS_ENTITY edge is lexical provenance, never IMPROVES/PREDICTS.
    source = envelope.sources[0]
    hits = [n for n in nodes if any(alias_present(a, source.text) for a in n['aliases'])]
    with session() as s:
        for n in hits:
            s.run('MATCH (s:Study)-[:HAS_EXTRACTION]->(x:Extraction {id:$extraction}), (e:Entity {id:$entity}) MERGE (s)-[r:MENTIONS_ENTITY]->(e) SET r.method="exact_alias_in_source",r.source_hash=$hash,r.review_state="automated"', extraction=extraction_id, entity=n['id'], hash=source.sha256).consume()
    return len(hits)


def graph_stats(entity_id=''):
    """Aggregate counts from the graph this process reads. No credentials or question text."""
    import re
    with session() as s:
        one = lambda query, **kw: s.run(query, **kw).single()[0]
        data = dict(version='graph-stats-v2',
            entities=one('MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false RETURN count(e)'),
            entities_by_kind={r['kind']: r['n'] for r in s.run("MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false RETURN coalesce(e.kind, e.type) AS kind, count(e) AS n ORDER BY kind")},
            biomarkers=one("MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false AND (e:Biomarker OR e.kind='Biomarker') RETURN count(e)"),
            biomarkers_with_aliases=one("MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false AND (e:Biomarker OR e.kind='Biomarker') AND size(e.aliases)>=2 RETURN count(e)"),
            alias_nodes=one('MATCH (a:EntityAlias) RETURN count(a)'),
            temporary_entities=one('MATCH (e:Entity {ephemeral:true}) RETURN count(e)'),
            questions=one('MATCH (q:Question) RETURN count(q)'),
            studies=one('MATCH (s:Study) RETURN count(s)'),
            matcher_records=one('MATCH (r:MatcherRecord) RETURN count(r)'),
            entity_links=one('MATCH ()-[m:MENTIONS_ENTITY]->() RETURN count(m)'),
            findings=one('MATCH (f:Finding) RETURN count(f)'),
            findings_about_entities=one('MATCH (f:Finding)-[:ABOUT]->(:Entity) RETURN count(DISTINCT f)'),
            findings_by_kind={r['kind']: r['n'] for r in s.run('MATCH (f:Finding) RETURN coalesce(f.kind, f.observation_type) AS kind, count(f) AS n ORDER BY kind')},
            source_passages=one('MATCH (p:SourcePassage) RETURN count(p)'),
            dead_letters=one('MATCH (d:DeadLetter) RETURN count(d)'),
            molecular_edges={r['edge']: r['n'] for r in s.run('MATCH (:Entity)-[r:ENCODED_BY|VARIANT_OF|IN_PATHWAY|MEASURED_BY|RELATED_TO]->(:Entity) RETURN type(r) AS edge, count(r) AS n ORDER BY edge')})
        if re.fullmatch(r'[a-z_]+:[a-z0-9-]{1,80}', entity_id or ''):
            profile = graph_entity(entity_id, s)
            data['entity'] = None if profile is None else dict(id=entity_id, name=profile['entity']['name'], aliases=profile['entity']['aliases'], studies=profile['studies'],
                                                               findings=[dict(f['finding'], quote=f['quote'], pmid=f['pmid']) for f in profile['findings']], dead_letters=profile['dead_letters'])
    return data


def graph_entity(entity_id, open_session=None):
    """One entity's identity, five layers, findings with passages, molecular neighbours and dead-letters."""
    def load(s):
        row = s.run('MATCH (e:Entity {id:$id}) WHERE coalesce(e.ephemeral,false)=false RETURN e', id=entity_id).single()
        if not row:
            return None
        e = dict(row['e'])
        layers = s.run('MATCH (e:Entity {id:$id})-[:HAS_LAYER]->(l:LayerAssessment) RETURN l.layer AS layer, coalesce(l.n_findings,0) AS n_findings, l.direction AS direction, l.sentences AS sentences, l.status AS status, l.review_state AS review_state', id=entity_id).data()
        found = s.run('MATCH (e:Entity {id:$id})<-[:ABOUT]-(f:Finding) OPTIONAL MATCH (f)-[:EVIDENCED_BY]->(p:SourcePassage) OPTIONAL MATCH (st:Study)-[:REPORTS]->(f) '
                      'OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)-[:SUPPORTED_BY]->(f) '
                      'RETURN f{.id, .kind, .measure, .estimate, .lower, .upper, .level, .unit, .cutoff, .cutoff_unit, .assay, .population, .setting, .target, .comparator, .statement, .p_value, .p_operator, .marker, .synthesis, .review_state} AS finding, '
                      'p.quote AS quote, p.locator AS locator, st.id AS study_id, st.pmid AS pmid, st.title AS title, st.year AS year, coalesce(l.layer, f.layer) AS layer ORDER BY st.year DESC LIMIT 200', id=entity_id).data()
        related = s.run('MATCH (e:Entity {id:$id})-[r:ENCODED_BY|VARIANT_OF|IN_PATHWAY|MEASURED_BY|RELATED_TO]-(o:Entity) WHERE coalesce(o.ephemeral,false)=false '
                        'RETURN type(r) AS edge, r.reason AS reason, o.id AS id, o.name AS name, coalesce(o.kind,o.type) AS kind, startNode(r)=e AS outgoing LIMIT 40', id=entity_id).data()
        studies = s.run('MATCH (e:Entity {id:$id})<-[:MENTIONS_ENTITY]-(st:Study) RETURN count(DISTINCT st) AS n', id=entity_id).single()['n']
        dead = s.run('MATCH (d:DeadLetter)-[:ABOUT]->(e:Entity {id:$id}) RETURN d.pmid AS pmid, d.code AS code, d.reasons AS reasons, d.excluded AS excluded, d.at AS at ORDER BY d.at DESC LIMIT 10', id=entity_id).data()
        return dict(version='graph-entity-v1',
                    entity=dict(id=e['id'], name=e['name'], kind=e.get('kind') or cypher.KIND.get(e.get('type'), 'Biomarker'), type=e.get('type'), aliases=e.get('aliases', []), review_state=e.get('review_state'),
                                last_extracted_at=e.get('last_extracted_at'), external_ids={k: e[k] for k in cypher.EXTERNAL_IDS if e.get(k)},
                                identity={k: e[k] for k in cypher.IDENTITY_FIELDS if e.get(k)},
                                locus={k: e[k] for k in cypher.LOCUS_FIELDS if e.get(k) is not None} or None),
                    layers=[dict(l, sentences=json.loads(l['sentences']) if l['sentences'] else []) for l in sorted(layers, key=lambda l: LAYERS.index(l['layer']) if l['layer'] in LAYERS else 9)],
                    findings=found, related=related, studies=studies,
                    dead_letters=[dict(d, reasons=json.loads(d['reasons']) if d['reasons'] else {},
                                       # The markers a rejected paper did measure: without them "findings about other
                                       # markers" is unreadable, and the reader cannot judge the call for themselves.
                                       excluded=[x.get('marker') for x in (json.loads(d['excluded']) if d['excluded'] else []) if isinstance(x, dict) and x.get('marker')][:6])
                                  for d in dead])
    if open_session is not None:
        return load(open_session)
    with session() as s:
        return load(s)


def graph_library():
    """Library feed: registry biomarkers with layer rollups and study counts."""
    with session() as s:
        return s.run("MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false AND (e.kind IN ['Biomarker','Gene','Variant','Protein','Test','Assay','PrecisionContext'] OR e.type IN ['biomarker','gene','variant','protein','test','assay','precision_context']) "
                     'OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment) '
                     'WITH e, sum(coalesce(l.n_findings,0)) AS findings, collect(CASE WHEN coalesce(l.n_findings,0)>0 THEN l.layer END) AS layers, collect(l.sentences) AS sentences '
                     'OPTIONAL MATCH (e)<-[:ABOUT]-(f:Finding) '
                     # Utility is a kind, never a layer. A trial of a drug is interventional evidence about the
                     # drug; only a finding that measured what testing changed is clinical utility, and counting
                     # the layer instead would let a drug's safety odds ratio fill the utility rung.
                     'WITH e, findings, layers, sentences, collect(coalesce(f.kind, f.observation_type)) AS kinds, '
                     "     sum(CASE WHEN coalesce(f.kind, f.observation_type)='utility' THEN 1 ELSE 0 END) AS utility_findings, "
                     "     sum(CASE WHEN f.layer IN ['interventional','guidelines'] THEN 1 ELSE 0 END) AS trial_findings "
                     'OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(st:Study) '
                     'RETURN e.id AS id, e.name AS name, e.kind AS kind, e.type AS type, e.aliases AS aliases, e.last_extracted_at AS last_extracted_at, findings, layers, sentences, kinds, utility_findings, trial_findings, count(DISTINCT st) AS studies').data()
