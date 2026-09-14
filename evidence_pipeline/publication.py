"""Read-only bridge from ingested PICO artifacts to Clarity's display contract.

Graph ingestion is necessary but not sufficient for plotting. The existing
visual release validator additionally checks context, metric and interval tuples.
"""

import json
import os
import time
from functools import lru_cache
from .state import State
from .schemas.pico import ExtractionEnvelope

# Explicit catalog bindings, matched against source-backed terms, never query hits.
ALIASES = {
    "compound:creatine": {
        "creatine",
        "CrM",
        "creatine monohydrate",
        "creatine monohydrate - Creapure®",
        "creatine ethyl ester",
        "creatine hydrochloride",
    },
    "compound:creatine-monohydrate": {
        "creatine monohydrate",
        "creatine monohydrate - Creapure®",
        "CrM",
    },
    "entity:egfr-osimertinib": {
        "osimertinib",
        "osimertinib plus chemotherapy",
        "osimertinib monotherapy",
    },
    "entity:alk-alectinib": {"alectinib"},
}
METRICS = {
    "hazard_ratio": "hazard ratio",
    "risk_ratio": "risk ratio",
    "odds_ratio": "odds ratio",
    "rate_ratio": "rate ratio",
    "mean_difference": "mean difference",
    "standardized_mean_difference": "standardized mean difference",
    "risk_difference": "risk difference",
    "sensitivity": "sensitivity",
    "specificity": "specificity",
}


def target_ids(extraction):
    names = {e.name.value.casefold() for e in extraction.exposures if e.name.value}
    return [
        target
        for target, aliases in ALIASES.items()
        if names & {a.casefold() for a in aliases}
    ]


def public_records(state):
    ingested = {r["id"] for r in state.all("graph_receipt")}
    ingested |= {r["extraction_key"] for r in state.all("ingestion")}
    ingested |= {
        r["extraction_key"]
        for r in state.all("job")
        if r.get("status") == "ingested" and r.get("extraction_key")
    }
    candidates = {c["study_id"]: c for c in state.all("candidate")}
    latest = {}
    for record in state.all("extraction"):
        if record["id"] not in ingested:
            continue
        try:
            envelope = ExtractionEnvelope.model_validate_json(
                json.dumps(record["envelope"])
            )
        except (ValueError, TypeError):
            continue
        source = next((s for s in envelope.sources if s.pmid), None)
        if not source or envelope.provider == "fixture":
            continue
        candidate = candidates.get("pmid:" + source.pmid, {})
        metadata = candidate.get("metadata", {})
        if "retract" in str(metadata.get("pubTypeList", "")).lower():
            continue
        item = {
            "id": record["id"],
            "envelope": envelope,
            "source": source,
            "metadata": metadata,
            "targets": target_ids(envelope.extraction),
            "grounding": record.get("grounding", {}),
        }
        previous = latest.get(source.pmid)
        if (
            previous is None
            or envelope.extracted_at > previous["envelope"].extracted_at
        ):
            latest[source.pmid] = item
    return list(latest.values())


def source_summary(item):
    env, source = item["envelope"], item["source"]
    return {
        "id": source.pmid,
        "pmid": source.pmid,
        "title": item["metadata"].get("title") or source.text.split("\n", 1)[0],
        "year": item["metadata"].get("pubYear"),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{source.pmid}/",
        "layer": "interventional"
        if env.extraction.study_design.startswith("rct_")
        else "synthesis"
        if env.extraction.study_design == "meta_analysis"
        else "unclassified",
        "targets": item["targets"],
        "extractionId": item["id"],
        "extractedAt": env.extracted_at.isoformat(),
        "sourceHash": source.sha256,
        "validation": "Automated source validation",
        "outcomes": len(env.extraction.outcomes),
        "reportedEstimates": sum(
            r.estimate.value is not None for r in env.extraction.results
        ),
    }


def visual_rows(item):
    from evidence.visual_report import release

    env, source = item["envelope"], item["source"]
    pico = env.extraction
    populations = {p.id: p for p in pico.populations}
    arms = {a.id: a for a in pico.arms}
    exposures = {e.id: e for e in pico.exposures}
    outcomes = {o.id: o for o in pico.outcomes}
    rows, exclusions = [], []

    def value(fact):
        return fact.value if fact else None

    def span(fact):
        if not fact or not fact.evidence:
            return None
        q = next((p for p in fact.evidence if p.source_id == source.id), None)
        return (
            {
                "source_id": "pmid:" + source.pmid,
                "start": q.start,
                "end": q.end,
                "text": q.quote,
            }
            if q
            else None
        )

    def arm_name(arm_id):
        arm = arms.get(arm_id)
        if not arm:
            return None
        names = []
        for i in arm.exposure_ids:
            if i not in exposures:
                continue
            exposure = exposures[i]
            name = value(exposure.name)
            doses = [
                d.dose.amount.raw + " " + d.dose.unit.raw
                for d in exposure.dosing
                if d.dose.amount.raw and d.dose.unit.raw
            ]
            names.append(name + " (" + "; ".join(doses) + ")" if name and doses else name)
        return " + ".join(names) if names and all(names) else value(arm.label)

    for result in pico.results:
        outcome, population = (
            outcomes.get(result.outcome_id),
            populations.get(result.population_id),
        )
        q = span(result.estimate)
        if (
            not outcome
            or not population
            or not outcome.name.value
            or not q
            or result.metric not in METRICS
        ):
            exclusions.append(
                {"result_id": result.id, "reason": "plot_context_or_metric_unavailable"}
            )
            continue
        # No transformation from log estimates, IQRs, predictions or p-values to CI.
        if result.scale != "natural":
            exclusions.append({"result_id": result.id, "reason": "non_natural_scale"})
            continue
        ci = next((i for i in result.intervals if i.kind == "confidence"), None)
        lower, upper, level = (
            (value(ci.lower), value(ci.upper), value(ci.level_percent))
            if ci
            else (None, None, None)
        )
        summary = source_summary(item)
        study = {
            **summary,
            "abstract": source.text,
            "population": value(population.label),
            "population_span": span(population.label),
            "exposure": arm_name(result.index_arm_id),
            "comparator": arm_name(result.reference_arm_id),
            "scope_passage": span(result.contrast),
            "design": "randomized controlled trial"
            if summary["layer"] == "interventional"
            else pico.study_design.replace("_", " "),
            "extraction": {
                "source_sha256": source.sha256,
                "extracted_at": env.extracted_at.isoformat(),
            },
        }
        finding = {
            "outcome": outcome.name.value,
            "quote": q["text"],
            "source_span": q,
            "effect": {
                "measure": METRICS[result.metric],
                "origin": "reported",
                "estimate": value(result.estimate),
                "lower": lower,
                "upper": upper,
                "confidence_level": level,
                "units": value(result.unit),
            },
        }
        row, error = release(study, finding)
        if row:
            row["picoExtractionId"] = item["id"]
            row["picoResultId"] = result.id
            from evidence.visual_report import digest

            row.pop("hash", None)
            row["hash"] = digest(row)
            rows.append(row)
        else:
            exclusions.append({"result_id": result.id, "reason": error})
    return rows, exclusions


@lru_cache(maxsize=1)
def snapshot(bucket):
    location = os.getenv("PIPELINE_DATABASE_URL") or os.getenv(
        "PIPELINE_STATE_PATH", "research_state/pico.sqlite3"
    )
    state = State(location)
    try:
        return public_records(state)
    finally:
        state.close()


def current_records():
    return snapshot(int(time.time() // 60))


def augment_report(base, target_id):
    from evidence.visual_report import report, digest

    additions = [r for r in current_records() if target_id in r["targets"]]
    if not additions:
        return base
    base = base or report(target_id, target_id.split(":", 1)[-1], [])
    rows = {r["id"]: r for r in base["records"]}
    studies = {str(s["id"]).replace("pmid:", ""): s for s in base["studies"]}
    exclusions = []
    for item in additions:
        new_rows, withheld = visual_rows(item)
        for row in new_rows:
            rows[row["id"]] = row
        studies[item["source"].pmid] = source_summary(item)
        exclusions.extend(withheld)
    base["records"] = list(rows.values())
    base["studies"] = list(studies.values())
    base["pipeline"] = {
        "studies": len(additions),
        "plotExclusions": exclusions,
        "validation": "Automated source validation",
    }
    base["sourceDate"] = max(
        [base.get("sourceDate") or ""]
        + [r["envelope"].extracted_at.isoformat() for r in additions]
    )
    base.pop("hash", None)
    base["hash"] = digest(base)
    return base


def matcher_records():
    from evidence.matcher import tokens

    records = []
    for item in current_records():
        summary = source_summary(item)
        pico = item["envelope"].extraction
        names = [e.name.value for e in pico.exposures if e.name.value]
        population = next(
            (p.label.value for p in pico.populations if p.label.value), None
        )
        quotes = list(
            dict.fromkeys(p.quote for r in pico.results for p in r.estimate.evidence)
        )
        records.append(
            {
                "id": "pmid:" + summary["pmid"],
                "pmid": summary["pmid"],
                "title": summary["title"],
                "url": summary["url"],
                "design": pico.study_design,
                "population": population,
                "n": None,
                "layer": summary["layer"],
                "findings": [],
                "exposure": " + ".join(names),
                "comparator": None,
                "cohort_id": None,
                "entity_ids": item["targets"],
                "_passages": quotes,
                "_text": item["source"].text,
                "_tokens": tokens(summary["title"] + " " + item["source"].text),
                "agreement": "not_assessed",
                "review_status": "source_validated",
                "extraction_url": "/api/pico/studies/" + summary["pmid"],
            }
        )
    return records
