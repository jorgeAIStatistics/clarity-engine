"""Quarantine unsupported claims, with an explicit exclusion ledger.

This never repairs a scientific value. It removes unsupported fields and labels,
then subjects the remaining complete DTO to the approved validators. Original
provider output is retained separately; empty shells cannot pass eligibility.
"""

import copy
from pydantic import ValidationError
from ..common import PipelineError
from ..schemas.numeric_tokens import (
    parse_numeric_token,
    parse_count_token,
    verbatim_numeric_token,
)
from ..schemas.pico import (
    PICOExtraction,
    Interval,
    PValue,
    ArmResult,
    SampleSize,
    Demographic,
    StatisticalResult,
)
from .transport import expand_fields, hydrate
from .repair import apply_repair

VERSION = "quote-grounding-v3"


class GroundingError(PipelineError):
    """Safe machine-readable exclusion feedback for bounded structured repair."""

    def __init__(self, excluded):
        super().__init__("insufficient_source_grounded_pico")
        self.validation_issues = [
            {
                "loc": e.get("path", [e.get("kind"), e.get("key"), e.get("field")]),
                "type": "source_grounding_exclusion",
                "message": e["reason"],
            }
            for e in excluded
        ]


def ground_transport(original, schema, sources):
    payload = copy.deepcopy(original)
    excluded, fixes = [], []
    docs = {s.id: s.text for s in sources}
    passages = {p["id"]: p for p in payload["passages"]}
    facts = {f["id"]: f for f in payload["facts"]}
    # A unique exact quote has one possible locator. Preserve the original wire
    # and audit the index normalization; never disambiguate repeated passages.
    for passage in passages.values():
        text = docs.get(passage["source_id"], "")
        quote = passage["quote"]
        if (
            quote
            and text.find(quote) >= 0
            and text.find(quote, text.find(quote) + 1) < 0
            and passage["occurrence"] != 0
        ):
            excluded.append(
                {
                    "path": ["passages", passage["id"], "occurrence"],
                    "reason": "unique_exact_quote_locator_normalized",
                    "original_occurrence": passage["occurrence"],
                }
            )
            passage["occurrence"] = 0

    def source_passage(ident):
        passage = passages.get(ident)
        if not passage or passage["source_id"] not in docs or not passage["quote"]:
            return False
        text, quote = docs[passage["source_id"]], passage["quote"]
        starts = []
        start = 0
        while (start := text.find(quote, start)) >= 0:
            starts.append(start)
            start += 1
        return type(passage["occurrence"]) is int and 0 <= passage["occurrence"] < len(
            starts
        )

    def reason(ident, ref):
        if ident in {"not_reported", "not_applicable", "ambiguous"} or ident is None:
            return None
        fact = facts.get(ident)
        if not fact:
            return "undefined_fact_reference"
        evidence = [p for p in fact["evidence"] if source_passage(p)]
        if not evidence:
            return "no_exact_source_passage"
        raw = fact["raw"]
        value_type = next(
            b["type"]
            for b in schema["$defs"][ref]["properties"]["value"]["anyOf"]
            if b.get("type") != "null"
        )
        if (
            value_type in {"number", "integer"}
            and fact["missing_reason"] != "not_reached"
        ):
            raw = verbatim_numeric_token(raw, [passages[p]["quote"] for p in evidence])
            try:
                (parse_count_token if value_type == "integer" else parse_numeric_token)(
                    raw
                )
            except (ValueError, TypeError):
                return "unsupported_numeric_token"
        if not any(raw in passages[p]["quote"] for p in evidence):
            return "literal_not_in_cited_passage"
        # A mixture of valid and fabricated citations is still rejected; no silent relinking.
        if len(evidence) != len(fact["evidence"]):
            return "invalid_additional_source_passage"
        return None

    for obj in payload["objects"]:
        definition = schema["$defs"].get(obj["kind"], {}).get("properties", {})
        fields = expand_fields(obj["fields"])
        for name, value in fields.items():
            field_schema = definition.get(name, {})
            ref = field_schema.get("$ref", "").split("/")[-1]
            if ref.startswith("Reported_"):
                problem = reason(value, ref)
                if problem:
                    fixes.append(
                        {
                            "object_kind": obj["kind"],
                            "object_key": obj["key"],
                            "field": {
                                "name": name,
                                "kind": "text",
                                "text": "ambiguous",
                                "items": [],
                            },
                        }
                    )
                    excluded.append(
                        {
                            "kind": obj["kind"],
                            "key": obj["key"],
                            "field": name,
                            "fact_id": value,
                            "reason": problem,
                        }
                    )
            elif field_schema.get("type") == "array" and isinstance(value, list):
                item_ref = field_schema.get("items", {}).get("$ref", "").split("/")[-1]
                if item_ref.startswith("Reported_"):
                    kept = []
                    for ident in value:
                        problem = reason(ident, item_ref)
                        if problem:
                            excluded.append(
                                {
                                    "kind": obj["kind"],
                                    "key": obj["key"],
                                    "field": name,
                                    "fact_id": ident,
                                    "reason": problem,
                                }
                            )
                        else:
                            kept.append(ident)
                    if kept != value:
                        fixes.append(
                            {
                                "object_kind": obj["kind"],
                                "object_key": obj["key"],
                                "field": {
                                    "name": name,
                                    "kind": "list",
                                    "text": "",
                                    "items": kept,
                                },
                            }
                        )
        for label, evidence in [
            ("role", "role_evidence"),
            ("favorable_direction", "direction_evidence"),
        ]:
            if obj["kind"] == "OutcomeDefinition" and fields.get(label) not in {
                None,
                "not_reported",
            }:
                refs = fields.get(evidence, [])
                if (
                    not isinstance(refs, list)
                    or not refs
                    or not all(source_passage(p) for p in refs)
                ):
                    fixes.append(
                        {
                            "object_kind": obj["kind"],
                            "object_key": obj["key"],
                            "field": {
                                "name": label,
                                "kind": "text",
                                "text": "not_reported",
                                "items": [],
                            },
                        }
                    )
                    fixes.append(
                        {
                            "object_kind": obj["kind"],
                            "object_key": obj["key"],
                            "field": {
                                "name": evidence,
                                "kind": "list",
                                "text": "",
                                "items": [],
                            },
                        }
                    )
                    excluded.append(
                        {
                            "kind": obj["kind"],
                            "key": obj["key"],
                            "field": label,
                            "reason": "label_without_source_evidence",
                        }
                    )
    grounded = (
        apply_repair(payload, {"field_fixes": fixes, "facts": [], "passages": []})
        if fixes
        else payload
    )
    dto = hydrate(grounded, schema, sources)

    def checked(items, model, path):
        kept = []
        for index, item in enumerate(items):
            try:
                model.model_validate(item)
            except ValidationError as error:
                excluded.append(
                    {
                        "path": path + [index],
                        "reason": "invalid_statistical_record",
                        "errors": [
                            {
                                "loc": list(e["loc"]),
                                "type": e["type"],
                                "message": e["msg"],
                            }
                            for e in error.errors(
                                include_input=False, include_url=False
                            )
                        ],
                    }
                )
            else:
                kept.append(item)
        return kept

    for index, population in enumerate(dto["populations"]):
        population["sample_sizes"] = checked(
            population["sample_sizes"],
            SampleSize,
            ["populations", index, "sample_sizes"],
        )
        population["demographics"] = checked(
            population["demographics"],
            Demographic,
            ["populations", index, "demographics"],
        )
    for index, arm in enumerate(dto["arms"]):
        arm["sample_sizes"] = checked(
            arm["sample_sizes"], SampleSize, ["arms", index, "sample_sizes"]
        )
    for index, result in enumerate(dto["results"]):
        for field, model in [
            ("intervals", Interval),
            ("p_values", PValue),
            ("arm_results", ArmResult),
        ]:
            result[field] = checked(result[field], model, ["results", index, field])
    dto["results"] = checked(dto["results"], StatisticalResult, ["results"])
    for result in list(dto["results"]):
        has_number = (
            result["estimate"]["value"] is not None
            or any(p["value"]["value"] is not None for p in result["p_values"])
            or any(
                a[f]["value"] is not None
                for a in result["arm_results"]
                for f in ["mean", "median", "events"]
            )
        )
        if not has_number:
            dto["results"].remove(result)
            excluded.append(
                {
                    "path": ["results"],
                    "result_id": result["id"],
                    "reason": "no_numeric_outcome_reported",
                }
            )
    # Do not keep synthesis summaries whose result was excluded.
    result_ids = {r["id"] for r in dto["results"]}
    for synthesis in list(dto["reported_syntheses"]):
        if synthesis["result_id"] not in result_ids:
            dto["reported_syntheses"].remove(synthesis)
            excluded.append(
                {
                    "path": ["reported_syntheses"],
                    "reason": "result_excluded",
                    "result_id": synthesis["result_id"],
                }
            )
    extraction = PICOExtraction.model_validate(dto)
    quantitative = any(
        r.estimate.value is not None
        or any(p.value.value is not None for p in r.p_values)
        or any(
            any(getattr(a, f).value is not None for f in ["mean", "median", "events"])
            for a in r.arm_results
        )
        for r in extraction.results
    )
    sample_size = any(
        n.count.value is not None and n.count.value > 0
        for p in extraction.populations
        for n in p.sample_sizes
    )
    if not (
        (any(p.label.value for p in extraction.populations) or sample_size)
        and any(e.name.value for e in extraction.exposures)
        and any(o.name.value for o in extraction.outcomes)
        and (quantitative or sample_size)
    ):
        raise GroundingError(excluded)
    return extraction, excluded
