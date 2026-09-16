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
EXTERNAL_IDS = ("hgnc", "uniprot", "ensembl", "mondo", "chebi", "ncit")
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
       .assay, .population, .setting, .target, .statement, .p_value, .review_state} AS finding,
       p.quote AS quote, s.id AS study_id, s.pmid AS pmid, s.title AS title
ORDER BY entity_id, layer
LIMIT 400"""

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
