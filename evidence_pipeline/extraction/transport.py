"""Compact strict wire grammar; hydrate literal facts into the approved PICO DTO.

Shared fact and passage tables prevent exponential grammar expansion. Numbers
are parsed from exact source tokens, and offsets are located deterministically.
The complete approved schema and source validators still gate every artifact.
"""

import copy
import re
from ..common import PipelineError
from ..schemas.numeric_tokens import (
    parse_numeric_token,
    parse_count_token,
    verbatim_numeric_token,
)

VERSION = "pico-fact-table-v6"
MISSING = {"not_reported", "not_applicable", "ambiguous"}


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def reference_schema(schema):
    pico = copy.deepcopy(schema)
    definitions = pico.pop("$defs")
    definitions = {
        k: v
        for k, v in definitions.items()
        if not k.startswith("Reported_") and k != "EvidenceSpan"
    }

    def rewrite(node):
        if isinstance(node, dict):
            ref = node.get("$ref", "").split("/")[-1]
            if ref.startswith("Reported_"):
                return {
                    "type": "string",
                    "description": "Fact ID or not_reported / not_applicable / ambiguous.",
                }
            if ref == "EvidenceSpan":
                return {"type": "string", "description": "Passage ID."}
            if ref:
                return {"type": "string", "description": "Key in objects." + ref + "."}
            return {k: rewrite(v) for k, v in node.items()}
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node

    passage = obj(
        {
            "id": {"type": "string"},
            "source_id": {"type": "string"},
            "quote": {"type": "string"},
            "occurrence": {"type": "integer", "minimum": 0},
            "section": schema["$defs"]["EvidenceSpan"]["properties"]["section"],
        }
    )
    fact = obj(
        {
            "id": {"type": "string"},
            "raw": {"type": "string"},
            "missing_reason": {"enum": ["none", "not_reached"]},
            "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}},
        }
    )
    root = obj(
        {
            "pico": rewrite(pico),
            "facts": {"type": "array", "items": fact},
            "passages": {"type": "array", "items": passage},
            "objects": obj(
                {
                    name: {
                        "type": "array",
                        "items": obj(
                            {"key": {"type": "string"}, "value": rewrite(definition)}
                        ),
                    }
                    for name, definition in definitions.items()
                }
            ),
        }
    )
    return root


def compact_schema(schema):
    reference = reference_schema(schema)
    field = obj(
        {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["text", "list", "null"]},
            "text": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}},
        }
    )
    fields = {"type": "array", "items": field}
    properties = reference["properties"]
    return obj(
        {
            "pico": fields,
            "facts": properties["facts"],
            "passages": properties["passages"],
            "objects": {
                "type": "array",
                "items": obj(
                    {
                        "kind": {
                            "type": "string",
                            "enum": list(properties["objects"]["properties"]),
                        },
                        "key": {"type": "string"},
                        "fields": fields,
                        "not_reported": {"type": "array", "items": {"type": "string"}},
                        "empty_lists": {"type": "array", "items": {"type": "string"}},
                        "null_fields": {"type": "array", "items": {"type": "string"}},
                    }
                ),
            },
        }
    )


def expand_fields(fields):
    result = {}
    for field in fields:
        if set(field) != {"name", "kind", "text", "items"} or field["name"] in result:
            raise PipelineError("invalid_transport_field")
        kind = field["kind"]
        if kind == "text" and field["items"] == [] and isinstance(field["text"], str):
            value = field["text"]
        elif (
            kind == "list" and field["text"] == "" and isinstance(field["items"], list)
        ):
            if not all(isinstance(x, str) for x in field["items"]):
                raise PipelineError("invalid_transport_field")
            value = field["items"]
        elif kind == "null" and field["text"] == "" and field["items"] == []:
            value = None
        else:
            raise PipelineError("invalid_transport_field")
        result[field["name"]] = value
    return result


TRANSPORT_INSTRUCTIONS = """
Transport format: return {pico, facts, passages, objects} using the strict tool schema.
Encode pico as a list of named fields. Encode objects as a flat list of records
{kind: exact type name, key: reference key, fields: list of named fields,
not_reported: field names whose value is not_reported,
empty_lists: field names whose value is [], null_fields: field names whose value is null}.
Use these three compact lists for ALL unknown/empty/null object fields to save tokens.
Each field must be declared exactly once, either in fields or one compact list.
A named field is {name, kind, text, items}. kind=text uses text and empty items;
kind=list uses items and empty text; kind=null uses empty text and empty items.
The reference schema below describes the expanded form. Include every required
field exactly once; the server expands your field lists and validates that schema.
Do not put JSON strings in text. Lists contain only literal strings or object keys.
The expanded reference schema is documentation ONLY. Do not return its {key,value}
tables; return the flat wire objects list with {kind,key,fields,not_reported,empty_lists,null_fields}.
CRITICAL: if a field name occurs in not_reported, empty_lists or null_fields,
DO NOT also include it in fields. Every field is declared ONCE total.
Each non-null structural reference MUST resolve to an objects record of the
correct kind. For example Dosing.dose and Dosing.duration are Quantity keys,
NEVER not_reported. When their values are unknown, create a Quantity with amount
and unit in its not_reported list. Only Reported fields and enums permitting
not_reported may use that marker. Do not use it in structural reference fields.
Nested objects and top-level pico array entries reference those table keys.
For example pico.populations contains keys in objects.Population.
No structural object is embedded inline: use a table key whenever requested.
The pico object has the approved structure, but every Reported field is a fact
ID and every EvidenceSpan is a passage ID. Use shared facts and passages.
For absent facts use the literal ID not_reported, not_applicable, or ambiguous.
Every Reported reference must point to a defined facts ID, never a raw inline
value. Quantity.amount and Quantity.unit are fact IDs. Interval.method is a fact
ID. Ensure ALL referenced fact IDs occur in facts, and all passage IDs exist.
A facts entry contains the exact raw numeric token or exact text phrase, its
passage IDs, confidence, and missing_reason none (or not_reached). Numeric raw
excludes units, comparison operators and percent signs. Do not round or compute.
Values and source offsets will be parsed by the server, not guessed by you.
A passage contains an exact, contiguous quote and zero-based occurrence in its
source document (usually 0). Never paraphrase a passage. Use abstract for abstract
body passages and title for titles. Local IDs must be stable across all links.
Do not omit reported PICO facts or statistics. Keep all source-specific outcomes,
contrasts, populations, timepoints and models separate. Null is only permitted
where the pico structure explicitly allows it; missing Reported facts use IDs.
"""


def hydrate(payload, schema, sources):
    if not isinstance(payload, dict) or set(payload) != {
        "pico",
        "facts",
        "passages",
        "objects",
    }:
        raise PipelineError("invalid_fact_table_transport")
    payload = copy.deepcopy(payload)
    payload["pico"] = expand_fields(payload["pico"])
    tables = {}
    for record in payload["objects"]:
        if set(record) != {
            "kind",
            "key",
            "fields",
            "not_reported",
            "empty_lists",
            "null_fields",
        }:
            raise PipelineError("invalid_transport_record")
        expanded = expand_fields(record["fields"])
        definition = schema["$defs"].get(record["kind"], {})
        properties = definition.get("properties", {})
        for name, value in list(expanded.items()):
            field_schema = properties.get(name, {})
            if value == "not_reported" and any(
                b.get("type") == "null" for b in field_schema.get("anyOf", [])
            ):
                expanded[name] = None
            elif (value is None or value == "not_reported") and field_schema.get(
                "type"
            ) == "array":
                expanded[name] = []
        for group, value in [
            ("not_reported", "not_reported"),
            ("empty_lists", []),
            ("null_fields", None),
        ]:
            for name in record[group]:
                if name not in properties:
                    raise PipelineError("unknown_transport_field")
                field_schema = properties[name]
                empty = value
                if group == "not_reported":
                    # All three encode absence, never a zero or an inferred fact.
                    # The approved field type determines its empty representation.
                    if field_schema.get("type") == "array":
                        empty = []
                    elif any(
                        b.get("type") == "null" for b in field_schema.get("anyOf", [])
                    ):
                        empty = None
                if name in expanded:
                    if expanded[name] != empty:
                        raise PipelineError("conflicting_transport_field")
                    continue  # Idempotent declarations of the same empty value.
                expanded[name] = copy.deepcopy(empty)
        tables.setdefault(record["kind"], []).append(
            {"key": record["key"], "value": expanded}
        )
    payload["objects"] = tables
    docs = {s.id: s for s in sources}
    passages, facts = {}, {}
    for p in payload["passages"]:
        if set(p) != {"id", "source_id", "quote", "occurrence", "section"}:
            raise PipelineError("invalid_transport_passage")
        if p["id"] in passages or p["source_id"] not in docs or not p["quote"]:
            raise PipelineError("invalid_transport_passage")
        if type(p["occurrence"]) is not int or p["occurrence"] < 0:
            raise PipelineError("invalid_passage_occurrence")
        text, quote = docs[p["source_id"]].text, p["quote"]
        starts = [m.start() for m in re.finditer("(?=" + re.escape(quote) + ")", text)]
        if p["occurrence"] >= len(starts):
            raise PipelineError("transport_quote_not_found")
        start = starts[p["occurrence"]]
        passages[p["id"]] = dict(
            source_id=p["source_id"],
            section=p["section"],
            start=start,
            end=start + len(quote),
            quote=quote,
            page=None,
            table_or_figure=None,
            row=None,
            column=None,
        )
    for f in payload["facts"]:
        if set(f) != {
            "id",
            "raw",
            "missing_reason",
            "extraction_confidence",
            "evidence",
        }:
            raise PipelineError("invalid_transport_fact")
        if f["id"] in facts or f["id"] in MISSING:
            raise PipelineError("duplicate_transport_fact")
        if f["missing_reason"] not in {"none", "not_reached"}:
            raise PipelineError("invalid_transport_missing_reason")
        facts[f["id"]] = f

    objects = {}
    for kind, entries in payload["objects"].items():
        if (
            kind not in schema["$defs"]
            or kind.startswith("Reported_")
            or kind == "EvidenceSpan"
        ):
            raise PipelineError("invalid_transport_object_kind")
        objects[kind] = {}
        for entry in entries:
            if set(entry) != {"key", "value"} or entry["key"] in objects[kind]:
                raise PipelineError("duplicate_transport_object")
            objects[kind][entry["key"]] = entry["value"]
    visiting = set()

    def walk(value, node):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name == "EvidenceSpan":
                if value not in passages:
                    raise PipelineError("unknown_transport_passage")
                return copy.deepcopy(passages[value])
            definition = schema["$defs"][name]
            if name.startswith("Reported_"):
                # A null wire cell explicitly carries no extracted fact. It never
                # becomes a numeric zero, an empty quote, or a source-backed claim.
                if value is None:
                    value = "not_reported"
                if value in MISSING:
                    return dict(
                        value=None,
                        raw=None,
                        missing_reason=value,
                        evidence=[],
                        extraction_confidence=None,
                    )
                if value not in facts:
                    raise PipelineError("unknown_transport_fact")
                f = facts[value]
                value_type = next(
                    x["type"]
                    for x in definition["properties"]["value"]["anyOf"]
                    if x.get("type") != "null"
                )
                raw = f["raw"]
                if value_type in {"integer", "number"}:
                    raw = verbatim_numeric_token(
                        raw,
                        [passages[p]["quote"] for p in f["evidence"] if p in passages],
                    )
                if f["missing_reason"] == "not_reached":
                    parsed = None
                elif value_type == "string":
                    parsed = raw
                elif value_type == "integer":
                    # Only grouped thousands or a literal integer; no truncation.
                    parsed = parse_count_token(raw)
                else:
                    try:
                        parsed = parse_numeric_token(raw)
                    except (ValueError, TypeError):
                        raise PipelineError("invalid_transport_number") from None
                return dict(
                    value=parsed,
                    raw=raw,
                    missing_reason=None
                    if f["missing_reason"] == "none"
                    else "not_reached",
                    evidence=[
                        walk(p, {"$ref": "#/$defs/EvidenceSpan"}) for p in f["evidence"]
                    ],
                    extraction_confidence=f["extraction_confidence"],
                )
            if value not in objects.get(name, {}):
                error = PipelineError("unknown_transport_object")
                error.validation_issues = [
                    {
                        "object_kind": name,
                        "object_key": value,
                        "code": "referenced_typed_object_missing",
                    }
                ]
                raise error
            marker = (name, value)
            if marker in visiting:
                raise PipelineError("cyclic_transport_object")
            visiting.add(marker)
            result = walk(objects[name][value], definition)
            visiting.remove(marker)
            return result
        if "anyOf" in node:
            if value is None and any(x.get("type") == "null" for x in node["anyOf"]):
                return None
            branches = [x for x in node["anyOf"] if x.get("type") != "null"]
            if len(branches) != 1:
                raise PipelineError("unsupported_transport_union")
            return walk(value, branches[0])
        if node.get("type") == "object":
            if not isinstance(value, dict) or set(value) != set(node["properties"]):
                raise PipelineError("invalid_transport_object")
            return {k: walk(v, node["properties"][k]) for k, v in value.items()}
        if node.get("type") == "array":
            if value is None or value == "not_reported":
                return []
            if not isinstance(value, list):
                raise PipelineError("invalid_transport_array")
            return [walk(v, node["items"]) for v in value]
        return value

    try:
        result = walk(payload["pico"], schema)
        # The wire tables may define a referenced record but omit it from a root
        # index. Close only explicit ID references to uniquely defined records.
        # No entity is invented, matched by name, or fetched from another source.
        kinds = {
            "populations": "Population",
            "exposures": "Exposure",
            "arms": "Arm",
            "outcomes": "OutcomeDefinition",
            "results": "StatisticalResult",
        }
        for _ in range(sum(len(v) for v in objects.values()) + 1):
            references = {
                "exposures": [e for a in result["arms"] for e in a["exposure_ids"]],
                "populations": [a["population_id"] for a in result["arms"]]
                + [r["population_id"] for r in result["results"]]
                + [p["parent_population_id"] for p in result["populations"]],
                "outcomes": [r["outcome_id"] for r in result["results"]],
                "arms": [
                    a
                    for r in result["results"]
                    for a in [r["index_arm_id"], r["reference_arm_id"]]
                    + [v["arm_id"] for v in r["arm_results"]]
                ],
                "results": [s["result_id"] for s in result["reported_syntheses"]],
            }
            added = False
            for root, ids in references.items():
                present = {v["id"] for v in result[root]}
                for ident in dict.fromkeys(ids):
                    if ident is None or ident in present:
                        continue
                    matches = [
                        key
                        for key, value in objects.get(kinds[root], {}).items()
                        if value.get("id") == ident
                    ]
                    if len(matches) > 1:
                        raise PipelineError("ambiguous_transport_reference")
                    if len(matches) == 1:
                        result[root].append(
                            walk(matches[0], {"$ref": "#/$defs/" + kinds[root]})
                        )
                        present.add(ident)
                        added = True
            if not added:
                break
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PipelineError("invalid_fact_table_transport") from None
