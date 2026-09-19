"""Cypher for the molecular evidence graph.

Question subgraphs start from (:Question)-[:MENTIONS]->(:Entity) only. Nothing here expands
through RELATED_TO, shared conditions or popularity, so a same-disease profile can never join a
question it was not named in. Writes preserve review_state "reviewed".
"""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta

LAYERS = ("mechanism", "preclinical", "observational", "interventional", "guidelines")
KIND = {
    "biomarker": "Biomarker", "compound": "Compound", "test": "Test", "precision_context": "PrecisionContext",
    "condition": "Condition", "gene": "Gene", "protein": "Protein", "variant": "Variant", "pathway": "Pathway",
    "assay": "Assay", "metabolite": "Metabolite",
}
RELATION_REASONS = {"same_outcome", "same_population", "predicts", "measures", "modifies_treatment", "same_gene", "same_pathway"}
# Curated identity, not findings: what the object is, where it is measured, and one background note.
IDENTITY_FIELDS = ("entity_class", "specimen", "pathway_note", "assay_hint", "identity_sentence")
EXTERNAL_IDS = ("hgnc", "uniprot", "ensembl", "ensembl_protein", "mondo", "chebi", "ncit")
# Where the gene sits, on a named assembly. Flat properties because Neo4j stores no nested map,
# and an assembly is stored with them because a coordinate without one is not a location.
LOCUS_FIELDS = ("assembly", "chrom", "start_bp", "end_bp", "gene_symbol")
KEEP_REVIEWED = "CASE WHEN {v}.review_state='reviewed' THEN 'reviewed' ELSE coalesce($review,'automated') END"


def norm_name(text):
    return re.sub(r"[^\w]+", " ", str(text).casefold()).strip()


# The brief's query patterns, kept verbatim so tests can check their shape.
RESOLVE_SPAN = """MATCH (a:EntityAlias)
WHERE a.norm_name = $norm
MATCH (a)<-[:HAS_ALIAS]-(e:Entity)
WHERE coalesce(e.ephemeral, false) = false
RETURN e
LIMIT 5"""

QUESTION_SUBGRAPH = """MATCH (q:Question {id:$qid})-[:MENTIONS]->(e:Entity)
OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)
OPTIONAL MATCH (l)-[:SUPPORTED_BY]->(f:Finding)
RETURN e, l, f"""

COVERAGE_PAYLOAD = """MATCH (q:Question {id:$qid})-[:MENTIONS]->(e)
MATCH (e)-[:HAS_LAYER]->(l)
RETURN e.id AS entity_id, e.name AS name, e.kind AS kind, l.layer AS layer, coalesce(l.n_findings, 0) AS n_findings,
       l.review_state AS review_state, l.direction AS direction, l.sentences AS sentences"""

CELL_FINDINGS = """MATCH (q:Question {id:$qid})-[:MENTIONS]->(e:Entity)-[:HAS_LAYER]->(l:LayerAssessment)-[:SUPPORTED_BY]->(f:Finding)
OPTIONAL MATCH (f)-[:EVIDENCED_BY]->(p:SourcePassage)
OPTIONAL MATCH (s:Study)-[:REPORTS]->(f)
RETURN e.id AS entity_id, l.layer AS layer, f{.id, .kind, .measure, .estimate, .lower, .upper, .level, .unit, .cutoff, .cutoff_unit,
       .assay, .population, .setting, .target, .statement, .p_value, .n, .synthesis, .provenance, .review_state} AS finding,
       p.quote AS quote, s.id AS study_id, s.pmid AS pmid, s.title AS title
ORDER BY entity_id, layer
LIMIT 400"""

# Catalog ordering and gap features count findings over (:Finding)-[:ABOUT]->(:Entity), the edge the
# publisher always writes, rather than over HAS_LAYER->SUPPORTED_BY, which is a rollup that a stale
# refresh can leave behind. On the live graph the two disagreed: 56 ABOUT edges against 50 rollup
# edges, the six missing ones being a meta-analysis whose findings had been dropped entirely.
# Ephemeral nodes are the throwaway spans of an unresolved question and are never catalog rows.
CATALOG_SORT = """MATCH (e:Entity)
WHERE coalesce(e.ephemeral, false) = false AND coalesce(e.kind, e.type) IN $kinds
OPTIONAL MATCH (e)<-[:ABOUT]-(f:Finding)
RETURN e.id AS id, e.name AS name, coalesce(e.kind, e.type) AS kind, count(DISTINCT f) AS n
ORDER BY n DESC, e.name"""

# One definition of an entity's graph features, shared by the exporter and the gap ranker so a
# queue row can be checked against a dated export without rerunning anything.
#
# Two counts are deliberately kept apart. n_utility is the utility KIND: a study that measured what
# testing changed. It is not "a trial exists" — a drug trial is interventional evidence about the
# drug, and counting the layer would let a safety odds ratio fill the utility rung. n_cited counts
# findings this entity is only QUOTED in; they carry no ABOUT edge and are not depth, so nothing
# that ranks need may read them as evidence already held.
GAP_FEATURES = """MATCH (e:Entity)
WHERE coalesce(e.ephemeral, false) = false
OPTIONAL MATCH (e)<-[:ABOUT]-(f:Finding)
WITH e, count(DISTINCT f) AS n_findings_linked,
     sum(CASE WHEN coalesce(f.provenance,'unclear') = 'primary' THEN 1 ELSE 0 END) AS n_primary,
     sum(CASE WHEN coalesce(f.provenance,'unclear') = 'unclear' THEN 1 ELSE 0 END) AS n_unclear,
     sum(CASE WHEN coalesce(f.kind, f.observation_type) = 'utility' THEN 1 ELSE 0 END) AS n_utility,
     sum(CASE WHEN coalesce(f.kind, f.observation_type) = 'discrimination' THEN 1 ELSE 0 END) AS n_discrimination,
     sum(CASE WHEN coalesce(f.kind, f.observation_type) = 'classification' THEN 1 ELSE 0 END) AS n_classification,
     sum(CASE WHEN f.layer IN ['interventional','guidelines'] THEN 1 ELSE 0 END) AS n_trial_layer
OPTIONAL MATCH (e)<-[:QUOTES]-(c:Finding)
WITH e, n_findings_linked, n_primary, n_unclear, n_utility, n_discrimination, n_classification,
     n_trial_layer, count(DISTINCT c) AS n_cited
OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(s:Study)
WITH e, n_findings_linked, n_primary, n_unclear, n_utility, n_discrimination, n_classification,
     n_trial_layer, n_cited, count(DISTINCT s) AS n_pubs
OPTIONAL MATCH (q:Question)-[:MENTIONS]->(e)
WITH e, n_findings_linked, n_primary, n_unclear, n_utility, n_discrimination, n_classification,
     n_trial_layer, n_cited, n_pubs, count(DISTINCT q) AS matcher_demand
OPTIONAL MATCH (e)<-[:ABOUT]-(d:DeadLetter)
RETURN e.id AS id, e.name AS name, coalesce(e.kind, e.type) AS kind,
       size(coalesce(e.aliases, [])) AS aliases, e.entity_class AS entity_class,
       n_findings_linked, n_primary, n_cited, n_unclear, n_utility,
       n_discrimination, n_classification, n_trial_layer, n_pubs, matcher_demand,
       count(DISTINCT d) AS dead_letters,
       (e.hgnc IS NOT NULL OR e.uniprot IS NOT NULL OR e.ensembl IS NOT NULL) AS has_ids
ORDER BY id"""

CLASSIFICATION_FINDINGS = """MATCH (e:Entity {name:$name})-[:HAS_LAYER]->(l)-[:SUPPORTED_BY]->(f:Finding {kind:'classification'})
RETURN f.measure AS measure, f.estimate AS estimate, f.cutoff AS cutoff, f.assay AS assay, f.population AS population"""


def entity_statements(node, registry_version="biomarkers-v2"):
    """Entity identity: kind label, aliases as EntityAlias nodes, external IDs, five layers."""
    kind = KIND[node["type"]]
    review = node.get("review_state", "automated")
    out = [(
        f"MERGE (e:Entity {{id:$id}}) SET e:{kind}, e.name=$name, e.aliases=$aliases, e.type=$type, e.kind=$kind, "
        "e.ephemeral=false, e.registry_version=$version, e.review_state=" + KEEP_REVIEWED.format(v="e"),
        dict(id=node["id"], name=node["name"], aliases=node["aliases"], type=node["type"], kind=kind, version=registry_version, review=review),
    )]
    identity = {k: node[k] for k in IDENTITY_FIELDS if node.get(k)}
    if identity:
        out.append(("MATCH (e:Entity {id:$id}) SET " + ", ".join(f"e.{k}=${k}" for k in identity), dict(id=node["id"], **identity)))
    ids = {k: node.get("external_ids", {}).get(k) for k in EXTERNAL_IDS if node.get("external_ids", {}).get(k)}
    if ids:
        out.append(("MATCH (e:Entity {id:$id}) SET " + ", ".join(f"e.{k}=${k}" for k in ids), dict(id=node["id"], **ids)))
    locus = node.get("locus") or {}
    place = {k: v for k, v in (("assembly", locus.get("assembly")), ("chrom", locus.get("chrom")),
                               ("start_bp", locus.get("start")), ("end_bp", locus.get("end")),
                               ("gene_symbol", locus.get("symbol"))) if v is not None}
    # A coordinate is only written with the assembly it was read on; without one it is not a place.
    if place.get("assembly") and place.get("chrom"):
        out.append(("MATCH (e:Entity {id:$id}) SET " + ", ".join(f"e.{k}=${k}" for k in place), dict(id=node["id"], **place)))
    for alias in dict.fromkeys(node["aliases"]):
        alias_id = "alias:" + hashlib.sha256((node["id"] + "|" + norm_name(alias)).encode()).hexdigest()[:24]
        out.append((
            "MATCH (e:Entity {id:$entity}) MERGE (a:EntityAlias {id:$id}) SET a.norm_name=$norm, a.name=$name, a.source=$source MERGE (e)-[:HAS_ALIAS]->(a)",
            dict(entity=node["id"], id=alias_id, norm=norm_name(alias), name=alias, source=node.get("alias_source", "registry")),
        ))
    for layer in LAYERS:
        out.append((
            "MATCH (e:Entity {id:$entity}) MERGE (l:LayerAssessment {id:$id}) ON CREATE SET l.layer=$layer, l.status='GAP', l.n_findings=0, l.review_state='automated' MERGE (e)-[:HAS_LAYER]->(l)",
            dict(entity=node["id"], id=node["id"] + ":" + layer, layer=layer),
        ))
    return out


def relation_statements(node, known_ids):
    """Molecular edges only between registry entities; reasons are a closed vocabulary."""
    out = []
    for field, edge in (("encoded_by", "ENCODED_BY"), ("variant_of", "VARIANT_OF"), ("in_pathway", "IN_PATHWAY"), ("measured_by", "MEASURED_BY")):
        for target in [node[field]] if isinstance(node.get(field), str) else node.get(field, []):
            if target in known_ids:
                out.append((f"MATCH (a:Entity {{id:$source}}), (b:Entity {{id:$target}}) MERGE (a)-[:{edge}]->(b)", dict(source=node["id"], target=target)))
    for related in node.get("related", []):
        if related.get("id") in known_ids and related.get("reason") in RELATION_REASONS:
            out.append((
                "MATCH (a:Entity {id:$source}), (b:Entity {id:$target}) MERGE (a)-[r:RELATED_TO]->(b) SET r.reason=$reason, r.review_state=" + KEEP_REVIEWED.format(v="r"),
                dict(source=node["id"], target=related["id"], reason=related["reason"], review="automated"),
            ))
    return out


def question_statements(text, intent, entity_ids, store_text=False, days=7):
    """A Question node and its MENTIONS edges. Raw question text is stored only when configured."""
    at = datetime.now(timezone.utc)
    qid = "question:" + hashlib.sha256(json.dumps([norm_name(text), sorted(entity_ids)]).encode()).hexdigest()[:24]
    out = [
        ("MATCH (q:Question) WHERE q.expires_at < $now DETACH DELETE q", dict(now=at.isoformat())),
        ("MERGE (q:Question {id:$qid}) SET q.parsed_json=$parsed, q.created_at=coalesce(q.created_at, $now), q.expires_at=$expiry, q.raw=$raw",
         dict(qid=qid, parsed=json.dumps(intent, ensure_ascii=False), now=at.isoformat(), expiry=(at + timedelta(days=days)).isoformat(), raw=text if store_text else None)),
    ]
    for entity_id in entity_ids:
        out.append(("MATCH (q:Question {id:$qid}), (e:Entity {id:$entity}) MERGE (q)-[:MENTIONS]->(e)", dict(qid=qid, entity=entity_id)))
    return qid, out


# A next step is a research design the map suggested, kept with the question that prompted it and
# expiring with it. It is a design to argue with, never advice about a person.
NEXT_STEP_FIELDS = ("title", "design", "population", "outcome", "comparator", "why", "rung")


def next_step_statements(question_id, payload, days=7):
    step_id = "nextstep:" + hashlib.sha256((question_id + "|" + str(payload.get("title", ""))).encode()).hexdigest()[:24]
    fields = {k: str(payload.get(k) or "")[:400] for k in NEXT_STEP_FIELDS}
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    statements = [(
        "MATCH (q:Question {id:$question}) MERGE (s:NextStep {id:$id}) "
        "SET s.title=$title, s.design=$design, s.population=$population, s.outcome=$outcome, "
        "s.comparator=$comparator, s.why=$why, s.rung=$rung, s.at=$at, s.expires_at=$expiry, s.review_state='automated' "
        "MERGE (s)-[:FOR]->(q)",
        dict(question=question_id, id=step_id, at=datetime.now(timezone.utc).isoformat(), expiry=expiry, **fields),
    )]
    for entity_id in list(payload.get("entity_ids") or [])[:8]:
        statements.append((
            "MATCH (s:NextStep {id:$id}), (e:Entity {id:$entity}) MERGE (s)-[:ABOUT]->(e)",
            dict(id=step_id, entity=entity_id),
        ))
    return step_id, statements


def run_all(session, statements):
    for query, parameters in statements:
        session.run(query, **parameters).consume()
