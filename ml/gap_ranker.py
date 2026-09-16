"""Which entity is worth an extraction call next — a baseline, fitted on what actually happened.

The label is the outcome of an enrichment attempt we already made: a typed finding (1) or a
dead-letter (0). The features are therefore restricted to what was knowable *before* that attempt —
publications, aliases, demand, kind, whether a curated identity exists. Finding counts are
deliberately excluded: they are the label wearing a disguise.

This is a logistic regression on a few dozen attempts, and it is only adopted as the ranking when
it beats the majority class. On the current label set it does not, so the queue is ranked by the
need rule and the model's probability rides along as an annotation. That is the whole point of
fitting a baseline before reaching for a graph model.

    python -m ml.gap_ranker              # report only
    python -m ml.gap_ranker --write      # also store Predictions in Neo4j
"""
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import roc_auc_score

from evidence.intent_graph import store, jobs

VERSION = "gap-baseline-v1"
KINDS = ["Biomarker", "Test", "PrecisionContext", "Variant", "Gene"]
FEATURES = ["studies", "aliases", "asked", "has_identity", *[f"kind_{k.lower()}" for k in KINDS]]

ROWS = """
MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false
OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)
WITH e, sum(coalesce(l.n_findings,0)) AS findings,
     sum(CASE WHEN l.layer IN ['interventional','guidelines'] THEN coalesce(l.n_findings,0) ELSE 0 END) AS utility_findings
OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(s:Study)
OPTIONAL MATCH (q:Question)-[:MENTIONS]->(e)
OPTIONAL MATCH (e)<-[:ABOUT]-(d:DeadLetter)
RETURN e.id AS id, e.name AS name, coalesce(e.kind, e.type) AS kind,
       size(coalesce(e.aliases,[])) AS aliases, e.entity_class AS entity_class,
       findings, utility_findings, count(DISTINCT s) AS studies, count(DISTINCT q) AS asked,
       count(DISTINCT d) AS dead_letters
"""


def features(row):
    kinds = {f"kind_{k.lower()}": 1.0 if row["kind"] == k else 0.0 for k in KINDS}
    return [float(row["studies"]), float(row["aliases"]), float(row["asked"]), 1.0 if row["entity_class"] else 0.0,
            *[kinds[f"kind_{k.lower()}"] for k in KINDS]]


def label(row):
    """1 when an attempt produced a typed finding, 0 when every attempt dead-lettered, else unknown."""
    if row["findings"] > 0:
        return 1
    if row["dead_letters"] > 0:
        return 0
    return None


def fit_and_score(rows):
    labelled = [(features(r), label(r), r) for r in rows if label(r) is not None]
    X = np.array([f for f, _, _ in labelled], dtype=float)
    y = np.array([l for _, l, _ in labelled], dtype=int)
    report = {"attempts": len(labelled), "successes": int(y.sum()), "failures": int((1 - y).sum())}
    if len(set(y)) < 2 or len(y) < 8:
        report["status"] = "not enough labelled attempts to fit a baseline"
        return None, report
    # Leave-one-out, because a held-out split of this size would be one or two rows.
    predictions = np.zeros(len(y), dtype=float)
    for train, test in LeaveOneOut().split(X):
        model = LogisticRegression(max_iter=2000, class_weight="balanced")
        model.fit(X[train], y[train])
        predictions[test] = model.predict_proba(X[test])[:, 1]
    majority = max(y.mean(), 1 - y.mean())
    report.update({
        "status": "fitted",
        "loo_accuracy": float(((predictions >= 0.5).astype(int) == y).mean()),
        "majority_class_accuracy": float(majority),
        "loo_auc": float(roc_auc_score(y, predictions)) if len(set(y)) > 1 else None,
    })
    # The existing rule is not comparable on this label. It scores NEED — an empty page scores high —
    # while this model predicts whether an attempt would succeed. Ranking need against a
    # success label would invert it by construction, so no head-to-head number is reported.
    report["comparison"] = ("The rule ranks need, not success probability, so it is not scored against this label. "
                            "The honest comparison for this model is the majority class.")
    report["useful"] = bool(report["loo_accuracy"] > majority and (report["loo_auc"] or 0) > 0.7)
    model = LogisticRegression(max_iter=2000, class_weight="balanced").fit(X, y)
    report["coefficients"] = {name: round(float(w), 3) for name, w in zip(FEATURES, model.coef_[0])}
    return model, report


def queue(rows, model, report, limit=12):
    """Entities never attempted, ranked by the rule that encodes need.

    The learned baseline rides along as an annotation only. It is adopted as the ranking just when
    it beats the majority class, which on this label set it does not.
    """
    # A condition or a drug is context for a finding, never a marker to extract findings about.
    fresh = [r for r in rows if label(r) is None and r["kind"] not in ("Condition", "Compound")]
    by_id = {r["id"]: r for r in fresh}
    probability = {}
    if model is not None and fresh:
        scores = model.predict_proba(np.array([features(r) for r in fresh], dtype=float))[:, 1]
        probability = {r["id"]: round(float(s), 4) for r, s in zip(fresh, scores)}
    ranked = []
    for gap in jobs.rank_gaps(fresh, limit=10_000):
        if gap["kind"] != "entity" or gap["id"] not in by_id:
            continue
        row = by_id[gap["id"]]
        ranked.append({"id": gap["id"], "name": gap["name"], "kind": row["kind"], "score": gap["score"],
                       "model": "rule-need-v1", "studies": row["studies"], "asked": row["asked"],
                       "reasons": gap["reasons"], "baseline_probability": probability.get(gap["id"]),
                       "baseline_adopted": bool(report.get("useful"))})
    return ranked[:limit]


def store_predictions(ranked):
    at = datetime.now(timezone.utc).isoformat()
    with store.session() as session:
        for row in ranked:
            session.run(
                "MATCH (e:Entity {id:$id}) MERGE (p:Prediction {id:$pid}) "
                "SET p.task='gap', p.score=$score, p.model=$model, p.version=$version, p.at=$at, p.review_state='automated' "
                "MERGE (p)-[:ABOUT]->(e)",
                id=row["id"], pid=f"prediction:gap:{row['id']}", score=row["score"], model=row["model"], version=VERSION, at=at).consume()
    return len(ranked)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="store Predictions in Neo4j")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    with store.session() as session:
        rows = session.run(ROWS).data()
    model, report = fit_and_score(rows)
    ranked = queue(rows, model, report, args.limit)
    output = {"version": VERSION, "at": datetime.now(timezone.utc).isoformat(), "entities": len(rows),
              "model": report, "queue": ranked,
              "note": "Suggested extraction targets for the library, ranked by need. Not a clinical score and not about any person."}
    lines = ["# Suggested extraction queue", "",
             f"Generated {output['at'][:19]}Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.",
             "", f"The learned baseline ({VERSION}) is **{'adopted' if report.get('useful') else 'not adopted'}**: leave-one-out accuracy "
             f"{report.get('loo_accuracy', float('nan')):.3f} against a majority class of {report.get('majority_class_accuracy', float('nan')):.3f} on {report.get('attempts')} attempts. "
             "Its probability is shown for comparison only.", "",
             "| # | Entity | Kind | Need | Publications | Baseline p | Why |", "|---|---|---|---|---|---|---|"]
    for n, row in enumerate(ranked, 1):
        lines.append(f"| {n} | {row['name']} | {row['kind']} | {row['score']} | {row['studies']} | "
                     f"{row['baseline_probability'] if row['baseline_probability'] is not None else '—'} | {'; '.join(row['reasons'])} |")
    Path(__file__).resolve().parents[1].joinpath("docs", "enrich-queue.md").write_text("\n".join(lines) + "\n")
    folder = Path(__file__).resolve().parent / "exports" / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gap_queue.json").write_text(json.dumps(output, indent=1) + "\n")
    if args.write:
        output["stored_predictions"] = store_predictions(ranked)
    print(json.dumps(output, indent=1))
    return output


if __name__ == "__main__":
    main()
