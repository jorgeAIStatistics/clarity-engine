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

from evidence.intent_graph import cypher, store

ROOT = Path(__file__).resolve().parent / "exports"

# The same feature definition the gap ranker reads, so a queue row can be checked against a
# dated export without rerunning anything.
ENTITIES = cypher.GAP_FEATURES

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
       f.lower AS lower, f.upper AS upper, f.unit AS unit, f.cutoff AS cutoff, f.n AS n,
       f.target AS target, f.population AS population, f.assay AS assay, f.marker AS marker,
       coalesce(f.provenance,'unclear') AS provenance, coalesce(f.synthesis,false) AS synthesis,
       f.review_state AS review_state, collect(DISTINCT e.id)[0] AS entity_id,
       f.layer AS layer, collect(DISTINCT l.layer)[0] AS rollup_layer,
       collect(DISTINCT st.id)[0] AS study_id, collect(DISTINCT st.pmid)[0] AS pmid
ORDER BY id
"""
# A number quoted from another paper: stored, never linked, and exported so a reader of the dump can
# see it was seen and set aside rather than missed.
QUOTED = """
MATCH (f:Finding {provenance:'cited'})
OPTIONAL MATCH (f)-[:QUOTES]->(e:Entity)
OPTIONAL MATCH (st:Study)-[:REPORTS]->(f)
RETURN f.id AS id, coalesce(f.kind, f.observation_type) AS kind, f.measure AS measure, f.estimate AS estimate,
       f.marker AS marker, f.target AS target, f.population AS population,
       collect(DISTINCT e.id)[0] AS quotes_entity_id, collect(DISTINCT st.id)[0] AS study_id,
       collect(DISTINCT st.pmid)[0] AS pmid
ORDER BY id
"""
DEAD_LETTERS = """
MATCH (d:DeadLetter)-[:ABOUT]->(e:Entity)
RETURN d.id AS id, e.id AS entity_id, d.pmid AS pmid, d.study_id AS study_id, d.code AS code,
       d.reasons AS reasons, d.excluded AS excluded, d.at AS at, d.review_state AS review_state
ORDER BY entity_id, at
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
TABLES = {"entities": ENTITIES, "aliases": ALIASES, "findings": FINDINGS, "quoted": QUOTED,
          "dead_letters": DEAD_LETTERS, "mentions": MENTIONS, "relations": RELATIONS, "questions": QUESTIONS}


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
    kinds, provenance = {}, {}
    for row in tables["findings"]:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        provenance[row["provenance"]] = provenance.get(row["provenance"], 0) + 1
    # LINKED findings, not every row. A cited finding is stored and carries no entity edge, so it is
    # not evidence the graph holds about anything and must not help a gate pass.
    linked = sum(1 for row in tables["findings"] if row["entity_id"])
    baseline = ROOT.parent / "gap_ranker.py"
    queue = Path(__file__).resolve().parents[1] / "docs" / "gap-queue.md"
    gate = {
        "entities_required": 200, "linked_findings_required": 200,
        "entities": counts["entities"], "findings_total": counts["findings"], "linked_findings": linked,
        "baseline_exists": baseline.exists() and queue.exists(),
        "split_plan": "by paper and by entity, so a GNN cannot be scored on findings from a study it trained on",
    }
    gate["passes"] = bool(gate["entities"] >= 200 and linked >= 200 and gate["baseline_exists"])
    manifest = {
        "version": "clarity-graph-export-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "findings_by_kind": dict(sorted(kinds.items())),
        "findings_by_provenance": dict(sorted(provenance.items())),
        "gnn_gate": gate,
        "note": "Aggregate published findings only. No patient-level data. review_state and provenance travel with every row.",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return folder, manifest


if __name__ == "__main__":
    folder, manifest = export()
    print(json.dumps({"folder": str(folder), **manifest}, indent=1))
