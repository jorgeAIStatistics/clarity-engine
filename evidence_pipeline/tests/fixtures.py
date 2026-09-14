"""Synthetic schema fixture, never imported into the evidence library."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib

TEXT = "SYNTHETIC TEST ONLY. Adults were randomized to Drug A versus placebo. Each arm analyzed 100 participants. The primary outcome was mortality. Hazard ratio 0.8 (95% confidence interval 0.6 to 1.1); p < 0.05."
SPAN = {
    "source_id": "fixture:1",
    "section": "abstract",
    "start": 0,
    "end": len(TEXT),
    "quote": TEXT,
    "page": None,
    "table_or_figure": None,
    "row": None,
    "column": None,
}


def missing():
    return {
        "value": None,
        "raw": None,
        "missing_reason": "not_reported",
        "evidence": [],
        "extraction_confidence": None,
    }


def fact(value):
    return {
        "value": value,
        "raw": str(value),
        "missing_reason": None,
        "evidence": [deepcopy(SPAN)],
        "extraction_confidence": None,
    }


def fixture():
    count = {"count": fact(100), "basis": "analyzed", "unit": "participants"}
    population = {
        "id": "p1",
        "parent_population_id": None,
        "label": fact("Adults"),
        "species": missing(),
        "conditions": [],
        "inclusion_criteria": [],
        "exclusion_criteria": [],
        "settings": [],
        "countries": [],
        "sample_sizes": [],
        "demographics": [],
    }
    exposures = [
        {
            "id": id,
            "kind": kind,
            "name": fact(name),
            "formulation": missing(),
            "dosing": [],
            "assay": missing(),
            "measurement_unit": missing(),
            "reference_category": missing(),
            "increment": None,
        }
        for id, kind, name in [("e1", "drug", "Drug A"), ("e2", "placebo", "placebo")]
    ]
    arms = [
        {
            "id": id,
            "label": fact(name),
            "population_id": "p1",
            "exposure_ids": [exposure],
            "sample_sizes": [deepcopy(count)],
            "period": missing(),
        }
        for id, name, exposure in [("a1", "Drug A", "e1"), ("a2", "placebo", "e2")]
    ]
    outcome = {
        "id": "o1",
        "name": fact("mortality"),
        "definition": missing(),
        "components": [],
        "instrument": missing(),
        "unit": missing(),
        "role": "primary",
        "role_evidence": [deepcopy(SPAN)],
        "favorable_direction": "not_reported",
        "direction_evidence": [],
    }
    interval = {
        "kind": "confidence",
        "lower": fact(0.6),
        "upper": fact(1.1),
        "level_percent": fact(95),
        "sidedness": "two_sided",
        "method": missing(),
    }
    p = {
        "comparator": "lt",
        "value": fact(0.05),
        "test": missing(),
        "sidedness": "not_reported",
        "multiplicity": "not_reported",
        "adjustment_method": missing(),
        "reported_alpha": missing(),
        "evidence": [deepcopy(SPAN)],
    }
    result = {
        "id": "r1",
        "outcome_id": "o1",
        "population_id": "p1",
        "index_arm_id": "a1",
        "reference_arm_id": "a2",
        "contrast": fact("Drug A versus placebo"),
        "timepoint": None,
        "followup": None,
        "analysis_set": missing(),
        "subgroup": [],
        "metric": "hazard_ratio",
        "metric_evidence": [deepcopy(SPAN)],
        "estimate": fact(0.8),
        "unit": missing(),
        "scale": "natural",
        "intervals": [interval],
        "p_values": [p],
        "standard_error": missing(),
        "adjusted": "not_reported",
        "covariates": [],
        "model": missing(),
        "arm_results": [],
        "estimate_origin": "reported",
    }
    return {
        "schema_version": "clarity-pico-1.0",
        "document_kind": "results_report",
        "study_design": "rct_parallel",
        "design_evidence": [deepcopy(SPAN)],
        "study_identifiers": [],
        "populations": [population],
        "exposures": exposures,
        "arms": arms,
        "outcomes": [outcome],
        "results": [result],
        "reported_syntheses": [],
        "methodology_facts": [],
    }


def source():
    return {
        "id": "fixture:1",
        "kind": "abstract",
        "pmid": None,
        "pmcid": None,
        "doi": None,
        "source_url": None,
        "version": "synthetic-v1",
        "retrieved_at": datetime(2026, 9, 13, tzinfo=timezone.utc),
        "text": TEXT,
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
