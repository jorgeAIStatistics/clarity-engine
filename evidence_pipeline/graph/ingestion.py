"""Transactional Neo4j projection of validated extracts, never causal inference."""

from typing import Literal
from ..common import digest, PipelineError
from ..schemas.pico import StrictModel, ExtractionEnvelope, EvidenceSpan, ID, Text
from ..extraction.service import SCHEMA_HASH


class EntityBinding(StrictModel):
    local_id: ID
    kind: Literal["Intervention", "Biomarker", "Condition"]
    node_id: ID
    reported_name: Text


LABELS = (
    "Study",
    "PublicationIdentifier",
    "Extraction",
    "SourceVersion",
    "SourceSpan",
    "Population",
    "Exposure",
    "StudyArm",
    "Outcome",
    "StatisticalResult",
    "EstimateInterval",
    "PValue",
)
CONSTRAINTS = [
    f"CREATE CONSTRAINT clarity_pico_{label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
    for label in LABELS
]
# Labels are constants; no label, property or Cypher fragment comes from the LLM.
BINDING_MATCH = {
    label: f"MATCH (n:{label} {{id:$id}}) RETURN count(n) AS count"
    for label in ("Intervention", "Biomarker", "Condition")
}
BINDING_WRITE = {
    "Intervention": "MATCH (e:Exposure {id:$local}), (n:Intervention {id:$node}), (s:Study {id:$study}) MERGE (e)-[:REFERS_TO]->(n) MERGE (s)-[:INVESTIGATES]->(n)",
    "Biomarker": "MATCH (e:Exposure {id:$local}), (n:Biomarker {id:$node}), (s:Study {id:$study}) MERGE (e)-[:REFERS_TO]->(n) MERGE (s)-[:INVESTIGATES]->(n)",
    "Condition": "MATCH (p:Population {id:$local}), (n:Condition {id:$node}), (s:Study {id:$study}) MERGE (p)-[:HAS_CONDITION]->(n) MERGE (s)-[:INVESTIGATES]->(n)",
}


def spans_of(model):
    found = {}

    def visit(value):
        if isinstance(value, EvidenceSpan):
            found[digest(value.model_dump(mode="json"))] = value
        elif hasattr(type(value), "model_fields"):
            for field in type(value).model_fields:
                visit(getattr(value, field))
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(model)
    return list(found.values())


def prepare(envelope, bindings):
    env = ExtractionEnvelope.model_validate_json(envelope.model_dump_json())
    if env.schema_sha256 != SCHEMA_HASH:
        raise PipelineError("unsupported_extraction_schema_hash")
    if env.provider == "fixture" or any(
        s.id.startswith("fixture:") for s in env.sources
    ):
        raise PipelineError("fixture_graph_ingestion_forbidden")
    if not env.sources:
        raise PipelineError("graph_source_missing")
    # One graph publication per artifact; multiple representations are allowed.
    pmids = {s.pmid for s in env.sources if s.pmid}
    dois = {s.doi.lower() for s in env.sources if s.doi}
    pmcids = {s.pmcid for s in env.sources if s.pmcid}
    if len(pmids) > 1 or len(dois) > 1 or len(pmcids) > 1:
        raise PipelineError("mixed_publications_in_artifact")
    aliases = sorted(
        ["pmid:" + x for x in pmids]
        + ["doi:" + x for x in dois]
        + ["pmcid:" + x for x in pmcids]
    )
    if not aliases:
        raise PipelineError("graph_publication_identifier_required")
    preferred = (
        "pmid:" + next(iter(pmids))
        if pmids
        else "doi:" + next(iter(dois))
        if dois
        else aliases[0]
    )
    extraction = env.extraction
    for b in bindings:
        if b.kind == "Condition":
            entity = next(
                (p for p in extraction.populations if p.id == b.local_id), None
            )
            if not entity or b.reported_name not in [
                c.value for c in entity.conditions
            ]:
                raise PipelineError("condition_binding_not_reported")
        else:
            entity = next((e for e in extraction.exposures if e.id == b.local_id), None)
            if not entity or entity.name.value != b.reported_name:
                raise PipelineError("exposure_binding_not_reported")
            if (b.kind == "Biomarker") != (entity.kind == "biomarker"):
                raise PipelineError("exposure_binding_kind_mismatch")
    identity = digest(
        {
            "sources": sorted((s.id, s.sha256) for s in env.sources),
            "extraction": extraction.model_dump(mode="json"),
            "schema": env.schema_sha256,
            "prompt": env.prompt_version,
            "provider": env.provider,
            "model": env.model,
        }
    )
    return env, identity, preferred, aliases


class Neo4jIngestor:
    def __init__(self, driver, database="neo4j"):
        self.driver = driver
        self.database = database

    def initialize(self):
        with self.driver.session(database=self.database) as session:
            for query in CONSTRAINTS:
                session.run(query).consume()

    def ingest(self, envelope, bindings=()):
        bindings = [
            EntityBinding.model_validate(
                b.model_dump() if isinstance(b, EntityBinding) else b
            )
            for b in bindings
        ]
        env, identity, preferred, aliases = prepare(envelope, bindings)
        with self.driver.session(database=self.database) as session:
            expected = ["clarity_pico_" + label.lower() + "_id" for label in LABELS]
            names = session.run(
                "SHOW CONSTRAINTS YIELD name WHERE name IN $names RETURN collect(name) AS names",
                names=expected,
            ).single()["names"]
            if set(names) != set(expected):
                raise PipelineError("graph_constraints_not_initialized")
            return session.execute_write(
                self._write, env, identity, preferred, aliases, bindings
            )

    @staticmethod
    def _write(tx, env, identity, preferred, aliases, bindings):
        # Validate existing domain nodes before any mutation in the transaction.
        for b in bindings:
            if tx.run(BINDING_MATCH[b.kind], id=b.node_id).single()["count"] != 1:
                raise PipelineError("graph_binding_missing_or_ambiguous")
        # Lock publication aliases in a consistent order before resolving identity.
        for alias in aliases:
            tx.run(
                "MERGE (i:PublicationIdentifier {id:$id}) SET i.lock_revision=coalesce(i.lock_revision,0)+1",
                id=alias,
            ).consume()
        existing = tx.run(
            "MATCH (i:PublicationIdentifier)-[:IDENTIFIES]->(s:Study) WHERE i.id IN $aliases RETURN collect(DISTINCT s.id) AS ids",
            aliases=aliases,
        ).single()["ids"]
        if len(existing) > 1:
            raise PipelineError("graph_publication_identity_conflict")
        study = existing[0] if existing else preferred
        tx.run(
            "MERGE (s:Study {id:$id}) ON CREATE SET s.created_at=$at",
            id=study,
            at=env.extracted_at.isoformat(),
            aliases=aliases,
        ).consume()
        for alias in aliases:
            tx.run(
                "MATCH (s:Study {id:$study}) MERGE (i:PublicationIdentifier {id:$id}) MERGE (i)-[:IDENTIFIES]->(s)",
                study=study,
                id=alias,
            ).consume()
        tx.run(
            'MATCH (s:Study {id:$study}) MERGE (x:Extraction {id:$id}) ON CREATE SET x.payload_json=$payload, x.created_at=$at, x.schema_hash=$schema, x.status="source_bound_extract" MERGE (s)-[:HAS_EXTRACTION]->(x)',
            study=study,
            id=identity,
            payload=env.model_dump_json(),
            at=env.extracted_at.isoformat(),
            schema=env.schema_sha256,
        ).consume()
        sources = {s.id: s for s in env.sources}
        for s in env.sources:
            sid = digest([s.id, s.sha256])
            tx.run(
                "MATCH (x:Extraction {id:$extraction}) MERGE (v:SourceVersion {id:$id}) ON CREATE SET v.text=$text, v.sha256=$hash, v.source_id=$source, v.url=$url, v.retrieved_at=$at MERGE (x)-[:EXTRACTED_FROM]->(v)",
                extraction=identity,
                id=sid,
                text=s.text,
                hash=s.sha256,
                source=s.id,
                url=s.source_url,
                at=s.retrieved_at.isoformat(),
            ).consume()
        prefix = lambda kind, id: identity + ":" + kind + ":" + id

        def attach_spans(owner_label, owner_id, obj):
            for span in spans_of(obj):
                s = sources[span.source_id]
                sid = digest([s.id, s.sha256])
                qid = digest([sid, span.start, span.end, span.quote])
                tx.run(
                    f"MATCH (n:{owner_label} {{id:$owner}}), (v:SourceVersion {{id:$source}}) MERGE (q:SourceSpan {{id:$id}}) ON CREATE SET q.start=$start, q.end=$end, q.quote=$quote, q.locator_json=$locator MERGE (q)-[:IN_SOURCE]->(v) MERGE (n)-[:SUPPORTED_BY]->(q)",
                    owner=owner_id,
                    source=sid,
                    id=qid,
                    start=span.start,
                    end=span.end,
                    quote=span.quote,
                    locator=span.model_dump_json(),
                ).consume()

        for collection, label, kind in (
            (env.extraction.populations, "Population", "population"),
            (env.extraction.exposures, "Exposure", "exposure"),
            (env.extraction.arms, "StudyArm", "arm"),
            (env.extraction.outcomes, "Outcome", "outcome"),
        ):
            for item in collection:
                local = prefix(kind, item.id)
                tx.run(
                    f"MATCH (x:Extraction {{id:$extraction}}) MERGE (n:{label} {{id:$id}}) ON CREATE SET n.local_id=$local, n.payload_json=$payload MERGE (x)-[:HAS_COMPONENT]->(n)",
                    extraction=identity,
                    id=local,
                    local=item.id,
                    payload=item.model_dump_json(),
                ).consume()
                name = getattr(item, "name", getattr(item, "label", None))
                if name and name.value is not None:
                    tx.run(
                        f"MATCH (n:{label} {{id:$id}}) SET n.reported_name=$name",
                        id=local,
                        name=name.value,
                    ).consume()
                attach_spans(label, local, item)
        for p in env.extraction.populations:
            if p.parent_population_id:
                tx.run(
                    "MATCH (p:Population {id:$child}), (parent:Population {id:$parent}) MERGE (p)-[:SUBGROUP_OF]->(parent)",
                    child=prefix("population", p.id),
                    parent=prefix("population", p.parent_population_id),
                ).consume()
        for arm in env.extraction.arms:
            tx.run(
                "MATCH (a:StudyArm {id:$arm}), (p:Population {id:$population}) MERGE (a)-[:IN_POPULATION]->(p)",
                arm=prefix("arm", arm.id),
                population=prefix("population", arm.population_id),
            ).consume()
            for exposure in arm.exposure_ids:
                tx.run(
                    "MATCH (a:StudyArm {id:$arm}), (e:Exposure {id:$exposure}) MERGE (a)-[:USES]->(e)",
                    arm=prefix("arm", arm.id),
                    exposure=prefix("exposure", exposure),
                ).consume()
        for r in env.extraction.results:
            rid = prefix("result", r.id)
            tx.run(
                'MATCH (x:Extraction {id:$extraction}), (s:Study {id:$study}), (o:Outcome {id:$outcome}), (p:Population {id:$population}) MERGE (r:StatisticalResult {id:$id}) ON CREATE SET r.payload_json=$payload, r.metric=$metric, r.estimate=$estimate, r.scale=$scale, r.status="reported_extract" MERGE (x)-[:HAS_RESULT]->(r) MERGE (s)-[:REPORTS]->(r) MERGE (r)-[:MEASURES]->(o) MERGE (r)-[:IN_POPULATION]->(p)',
                extraction=identity,
                study=study,
                outcome=prefix("outcome", r.outcome_id),
                population=prefix("population", r.population_id),
                id=rid,
                payload=r.model_dump_json(),
                metric=r.metric,
                estimate=r.estimate.value,
                scale=r.scale,
            ).consume()
            for arm, edge in (
                (r.index_arm_id, "INDEX_ARM"),
                (r.reference_arm_id, "REFERENCE_ARM"),
            ):
                if arm:
                    tx.run(
                        f"MATCH (r:StatisticalResult {{id:$result}}), (a:StudyArm {{id:$arm}}) MERGE (r)-[:{edge}]->(a)",
                        result=rid,
                        arm=prefix("arm", arm),
                    ).consume()
            for i, interval in enumerate(r.intervals):
                iid = rid + ":interval:" + str(i)
                tx.run(
                    "MATCH (r:StatisticalResult {id:$result}) MERGE (v:EstimateInterval {id:$id}) ON CREATE SET v.kind=$kind, v.lower=$lower, v.upper=$upper, v.level_percent=$level, v.sidedness=$sidedness MERGE (r)-[:HAS_INTERVAL]->(v)",
                    result=rid,
                    id=iid,
                    kind=interval.kind,
                    lower=interval.lower.value,
                    upper=interval.upper.value,
                    level=interval.level_percent.value,
                    sidedness=interval.sidedness,
                ).consume()
                attach_spans("EstimateInterval", iid, interval)
            for i, pvalue in enumerate(r.p_values):
                pid = rid + ":pvalue:" + str(i)
                tx.run(
                    "MATCH (r:StatisticalResult {id:$result}) MERGE (p:PValue {id:$id}) ON CREATE SET p.value=$value, p.comparator=$operator, p.multiplicity=$multiplicity, p.sidedness=$sidedness MERGE (r)-[:HAS_P_VALUE]->(p)",
                    result=rid,
                    id=pid,
                    value=pvalue.value.value,
                    operator=pvalue.comparator,
                    multiplicity=pvalue.multiplicity,
                    sidedness=pvalue.sidedness,
                ).consume()
                attach_spans("PValue", pid, pvalue)
            attach_spans("StatisticalResult", rid, r)
        attach_spans("Extraction", identity, env.extraction)
        for b in bindings:
            tx.run(
                BINDING_WRITE[b.kind],
                local=prefix(
                    "population" if b.kind == "Condition" else "exposure", b.local_id
                ),
                node=b.node_id,
                study=study,
            ).consume()
        return {
            "study_id": study,
            "extraction_id": identity,
            "results": len(env.extraction.results),
            "bindings": len(bindings),
        }
