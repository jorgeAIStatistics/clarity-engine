"""Dump the evidence graph to flat files for offline modelling.

Run locally, never from the web process: nothing here is imported by the Flask app, and
scikit-learn and friends stay out of the deployment. Every export is stamped with the date and
the counts it contains, so a model can name the snapshot it was fitted on.

    python -m ml.export            # writes ml/exports/<date>/
"""
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

from evidence.intent_graph import store

ROOT = Path(__file__).resolve().parent / "exports"

ENTITIES = """
MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false
OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)
WITH e, sum(coalesce(l.n_findings,0)) AS findings,
     sum(CASE WHEN l.layer IN ['interventional','guidelines'] THEN coalesce(l.n_findings,0) ELSE 0 END) AS utility_findings
OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(s:Study)
OPTIONAL MATCH (e)<-[:ABOUT]-(d:DeadLetter)
RETURN e.id AS id, e.name AS name, coalesce(e.kind, e.type) AS kind, e.review_state AS review_state,
       size(coalesce(e.aliases,[])) AS aliases, e.entity_class AS entity_class, e.specimen AS specimen,
       e.hgnc AS hgnc, e.uniprot AS uniprot, e.ensembl AS ensembl,
       findings, utility_findings, count(DISTINCT s) AS studies, count(DISTINCT d) AS dead_letters
ORDER BY id
"""
ALIASES = """
MATCH (e:Entity)-[:HAS_ALIAS]->(a:EntityAlias)
RETURN e.id AS entity_id, a.name AS alias, a.norm_name AS norm_name, coalesce(a.source,'registry') AS source
ORDER BY entity_id, norm_name
"""
FINDINGS = """
MATCH (f:Finding)
OPTIONAL MATCH (f)-[:ABOUT]->(e:Entity)
OPTIONAL MATCH (st:Study)-[:REPORTS]->(f)
OPTIONAL MATCH (:Entity)-[:HAS_LAYER]->(l:LayerAssessment)-[:SUPPORTED_BY]->(f)
RETURN f.id AS id, coalesce(f.kind, f.observation_type) AS kind, f.measure AS measure, f.estimate AS estimate,
       f.unit AS unit, f.cutoff AS cutoff, f.target AS target, f.population AS population, f.assay AS assay,
       f.review_state AS review_state, collect(DISTINCT e.id)[0] AS entity_id, collect(DISTINCT l.layer)[0] AS layer,
       collect(DISTINCT st.id)[0] AS study_id, collect(DISTINCT st.pmid)[0] AS pmid
ORDER BY id
"""
MENTIONS = """
MATCH (s:Study)-[m:MENTIONS_ENTITY]->(e:Entity)
RETURN s.id AS study_id, s.pmid AS pmid, e.id AS entity_id, m.method AS method, m.review_state AS review_state
ORDER BY study_id, entity_id
"""
RELATIONS = """
MATCH (a:Entity)-[r:ENCODED_BY|VARIANT_OF|IN_PATHWAY|MEASURED_BY|RELATED_TO]->(b:Entity)
RETURN a.id AS source, type(r) AS edge, coalesce(r.reason,'') AS reason, b.id AS target,
       coalesce(r.review_state,'automated') AS review_state
ORDER BY source, edge, target
"""
QUESTIONS = """
MATCH (q:Question)-[:MENTIONS]->(e:Entity)
RETURN q.id AS question_id, e.id AS entity_id, coalesce(e.ephemeral,false) AS temporary
ORDER BY question_id, entity_id
"""
TABLES = {"entities": ENTITIES, "aliases": ALIASES, "findings": FINDINGS, "mentions": MENTIONS, "relations": RELATIONS, "questions": QUESTIONS}


def write_table(folder, name, rows):
    path = folder / f"{name}.csv"
    if not rows:
        path.write_text("")
        return 0
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export(stamp=None):
    folder = ROOT / (stamp or date.today().isoformat())
    folder.mkdir(parents=True, exist_ok=True)
    counts, tables = {}, {}
    with store.session() as session:
        for name, query in TABLES.items():
            tables[name] = session.run(query).data()
    for name, rows in tables.items():
        counts[name] = write_table(folder, name, rows)
    kinds = {}
    for row in tables["findings"]:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    manifest = {
        "version": "clarity-graph-export-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "findings_by_kind": dict(sorted(kinds.items())),
        "gnn_gate": {"entities_required": 200, "typed_findings_required": 200,
                     "entities": counts["entities"], "typed_findings": counts["findings"],
                     "passes": counts["entities"] >= 200 and counts["findings"] >= 200},
        "note": "Aggregate published findings only. No patient-level data. review_state travels with every row.",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return folder, manifest


if __name__ == "__main__":
    folder, manifest = export()
    print(json.dumps({"folder": str(folder), **manifest}, indent=1))
