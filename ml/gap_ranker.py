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

from evidence.intent_graph import cypher, store

VERSION = "gap-baseline-v1"
KINDS = ["Biomarker", "Test", "PrecisionContext", "Variant", "Gene"]
FEATURES = ["studies", "aliases", "asked", "has_identity", *[f"kind_{k.lower()}" for k in KINDS]]

# Findings are counted over (:Finding)-[:ABOUT]->(:Entity), the edge the publisher always writes,
# not over the HAS_LAYER rollup: the two disagreed on the live graph, and an entity that looked
# empty because a rollup was stale would be ranked as a gap and extracted a second time.
# Two different counts, kept apart on purpose. utility_findings is the LAYER count, and the need
# rule's own wording ("no interventional or guideline findings") describes exactly that. The utility
# RUNG is a kind: a trial of a drug is not evidence that measuring the marker helps, so a pair with
# three interventional findings and no utility finding must still read as an empty utility rung.
# One definition, shared with the exporter, so a queue row can be checked against a dated export.
ROWS = cypher.GAP_FEATURES


def need(row):
    """Publications or demand high, linked findings low, and the utility rung empty.

    n_cited is not depth. A number this entity was only quoted in tells us nothing has been
    measured about it here, so it must not make an entity look already covered.
    """
    if row["n_utility"] > 0:
        return 0.0          # the rung this queue exists to fill is filled; spend the call elsewhere
    reach = row["n_pubs"] + 3 * row["matcher_demand"]
    return round(reach / (1.0 + row["n_findings_linked"]), 3)


def reasons(row):
    out = []
    if row["n_pubs"] and not row["n_findings_linked"]:
        out.append(f"{row['n_pubs']} publications indexed, no linked finding")
    elif row["n_pubs"]:
        out.append(f"{row['n_pubs']} publications against {row['n_findings_linked']} linked findings")
    if row["matcher_demand"]:
        out.append(f"asked in {row['matcher_demand']} recent question(s)")
    if row["n_cited"]:
        out.append(f"{row['n_cited']} quoted from other papers, which is not depth")
    if not row["n_utility"]:
        out.append("no utility finding")
    if not row["has_ids"]:
        out.append("no external identifier")
    return out


def features(row):
    kinds = {f"kind_{k.lower()}": 1.0 if row["kind"] == k else 0.0 for k in KINDS}
    return [float(row["n_pubs"]), float(row["aliases"]), float(row["matcher_demand"]), 1.0 if row["entity_class"] else 0.0,
            *[kinds[f"kind_{k.lower()}"] for k in KINDS]]


def label(row):
    """1 when an attempt produced a typed finding, 0 when every attempt dead-lettered, else unknown."""
    if row["n_findings_linked"] > 0:
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
    # Beating the majority class on a few dozen leave-one-out folds is weak evidence, so this gate
    # only ever earns the model a tie-break, never the ranking itself.
    report["useful"] = bool(report["loo_accuracy"] > majority and (report["loo_auc"] or 0) > 0.7)
    report["caveat"] = (f"Leave-one-out over {len(y)} attempts. The interval on an accuracy from this many folds is wide; "
                        "treat the comparison as a sanity check, not a measurement.")
    model = LogisticRegression(max_iter=2000, class_weight="balanced").fit(X, y)
    report["coefficients"] = {name: round(float(w), 3) for name, w in zip(FEATURES, model.coef_[0])}
    return model, report


def queue(rows, model, report, limit=20):
    """Entities never attempted, ranked by the rule that encodes need.

    Need stays the ranking, because a model that predicts which attempt will SUCCEED would rank the
    easy targets first and starve the gaps the library actually has. When the baseline beats the
    majority class it is used for one thing only: breaking ties between entities the rule scores
    equally, where "which of these is likeliest to return a finding" is exactly the open question.
    Every row carries the probability and whether it was allowed to matter, so the ordering can be
    read back.
    """
    # A condition or a drug is context for a finding, never a marker to extract findings about.
    fresh = [r for r in rows if label(r) is None and r["kind"] not in ("Condition", "Compound")]
    by_id = {r["id"]: r for r in fresh}
    probability = {}
    if model is not None and fresh:
        scores = model.predict_proba(np.array([features(r) for r in fresh], dtype=float))[:, 1]
        probability = {r["id"]: round(float(s), 4) for r, s in zip(fresh, scores)}
    ranked = []
    for row in sorted(fresh, key=lambda r: (-need(r), r["name"].casefold())):
        score = need(row)
        if score <= 0:
            continue
        ranked.append({"id": row["id"], "name": row["name"], "kind": row["kind"], "score": score,
                       "model": "rule-need-v2", "n_findings": row["n_findings_linked"],
                       "n_primary": row["n_primary"], "n_cited": row["n_cited"],
                       "n_utility": row["n_utility"], "studies": row["n_pubs"],
                       "asked": row["matcher_demand"], "has_ids": row["has_ids"],
                       "reasons": reasons(row), "baseline_probability": probability.get(row["id"]),
                       "baseline_breaks_ties": bool(report.get("useful"))})
    if report.get("useful"):
        ranked.sort(key=lambda r: (-r["score"], -(r["baseline_probability"] or 0.0), r["name"].casefold()))
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
    parser.add_argument("--limit", type=int, default=20)
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
             "", f"The learned baseline ({VERSION}) "
             + (f"**breaks ties** between entities the rule scores equally: leave-one-out accuracy "
                f"{report.get('loo_accuracy', float('nan')):.3f} against a majority class of "
                f"{report.get('majority_class_accuracy', float('nan')):.3f} on {report.get('attempts')} attempts "
                f"(AUC {report.get('loo_auc') or float('nan'):.3f}). It never sets the ranking: need does, because a model that "
                "predicts which attempt will succeed would rank the easy targets first and starve the real gaps."
                if report.get("useful") else
                f"is **not used**: leave-one-out accuracy {report.get('loo_accuracy', float('nan')):.3f} does not beat a majority "
                f"class of {report.get('majority_class_accuracy', float('nan')):.3f} on {report.get('attempts')} attempts. "
                "Its probability is shown for comparison only."),
             "", report.get("caveat", ""), "",
             "n_findings and n_utility are the counts the ranker read, so a row can be checked against the "
             "graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: "
             "a trial of a drug is not evidence that measuring the marker helps.", "",
             "| # | id | name | n_linked | n_primary | n_cited | n_utility | n_pubs | demand | need | baseline p | reason |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, row in enumerate(ranked, 1):
        lines.append(f"| {n} | `{row['id']}` | {row['name']} | {row['n_findings']} | {row['n_primary']} | "
                     f"{row['n_cited']} | {row['n_utility']} | {row['studies']} | {row['asked']} | {row['score']} | "
                     f"{row['baseline_probability'] if row['baseline_probability'] is not None else '—'} | {'; '.join(row['reasons'])} |")
    Path(__file__).resolve().parents[1].joinpath("docs", "gap-queue.md").write_text("\n".join(lines) + "\n")
    folder = Path(__file__).resolve().parent / "exports" / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gap_queue.json").write_text(json.dumps(output, indent=1) + "\n")
    if args.write:
        output["stored_predictions"] = store_predictions(ranked)
    print(json.dumps(output, indent=1))
    return output


if __name__ == "__main__":
    main()
