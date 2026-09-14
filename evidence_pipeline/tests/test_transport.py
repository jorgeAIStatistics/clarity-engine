import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from evidence_pipeline.common import PipelineError
from evidence_pipeline.config import Settings
from evidence_pipeline.extraction.transport import compact_schema, hydrate
from evidence_pipeline.extraction.service import SCHEMA
from evidence_pipeline.schemas.pico import SourceDocument, PICOExtraction
from evidence_pipeline.tests.fixtures import fixture, source


def encode(payload):
    """Independent test encoder: approved DTO -> compact wire payload."""
    tables, facts, passages = [], [], []

    def fields(data):
        return [
            dict(
                name=k,
                kind="null" if v is None else "list" if isinstance(v, list) else "text",
                text=v if isinstance(v, str) else "",
                items=v if isinstance(v, list) else [],
            )
            for k, v in data.items()
        ]

    def visit(value, node):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name == "EvidenceSpan":
                key = "span" + str(len(passages))
                passages.append(
                    dict(
                        id=key,
                        source_id=value["source_id"],
                        quote=value["quote"],
                        occurrence=0,
                        section=value["section"],
                    )
                )
                return key
            definition = SCHEMA["$defs"][name]
            if name.startswith("Reported_"):
                if value["raw"] is None:
                    return value["missing_reason"]
                key = "fact" + str(len(facts))
                refs = [
                    visit(p, {"$ref": "#/$defs/EvidenceSpan"})
                    for p in value["evidence"]
                ]
                facts.append(
                    dict(
                        id=key,
                        raw=value["raw"],
                        missing_reason=value["missing_reason"] or "none",
                        extraction_confidence=value["extraction_confidence"],
                        evidence=refs,
                    )
                )
                return key
            expanded = visit(value, definition)
            key = "object" + str(len(tables))
            tables.append(
                dict(
                    kind=name,
                    key=key,
                    fields=fields(
                        {
                            k: v
                            for k, v in expanded.items()
                            if v not in (None, "not_reported", [])
                        }
                    ),
                    not_reported=[
                        k for k, v in expanded.items() if v == "not_reported"
                    ],
                    empty_lists=[k for k, v in expanded.items() if v == []],
                    null_fields=[k for k, v in expanded.items() if v is None],
                )
            )
            return key
        if "anyOf" in node:
            return (
                None
                if value is None
                else visit(
                    value, next(x for x in node["anyOf"] if x.get("type") != "null")
                )
            )
        if node.get("type") == "object":
            return {k: visit(v, node["properties"][k]) for k, v in value.items()}
        if node.get("type") == "array":
            return [visit(v, node["items"]) for v in value]
        return value

    pico = visit(payload, SCHEMA)
    return dict(pico=fields(pico), objects=tables, facts=facts, passages=passages)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.dto = fixture()
        self.wire = encode(self.dto)
        self.sources = [SourceDocument.model_validate(source())]

    def test_exact_round_trip(self):
        result = hydrate(self.wire, SCHEMA, self.sources)
        self.assertEqual(result, self.dto)
        PICOExtraction.model_validate(result)

    def test_compact_grammar_has_no_deep_refs(self):
        schema = compact_schema(SCHEMA)
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertLess(len(json.dumps(schema)), 6000)

    def test_fabricated_quote_blocked(self):
        self.wire["passages"][0]["quote"] = "not in the source"
        with self.assertRaisesRegex(PipelineError, "quote_not_found"):
            hydrate(self.wire, SCHEMA, self.sources)

    def test_duplicate_fields_blocked(self):
        self.wire["pico"].append(deepcopy(self.wire["pico"][0]))
        with self.assertRaisesRegex(PipelineError, "invalid_transport_field"):
            hydrate(self.wire, SCHEMA, self.sources)

    def test_unknown_object_reference_blocked(self):
        next(x for x in self.wire["pico"] if x["name"] == "populations")["items"] = [
            "absent"
        ]
        with self.assertRaisesRegex(PipelineError, "unknown_transport_object"):
            hydrate(self.wire, SCHEMA, self.sources)

    def test_missing_required_field_blocked(self):
        self.wire["pico"] = [
            x for x in self.wire["pico"] if x["name"] != "study_design"
        ]
        with self.assertRaisesRegex(PipelineError, "invalid_transport_object"):
            hydrate(self.wire, SCHEMA, self.sources)

    def test_user_alias(self):
        with patch.dict("os.environ", {"NEO4J_USER": "neo4j"}, clear=True):
            self.assertEqual(Settings.from_env().neo4j_username, "neo4j")

    def test_username_precedence(self):
        with patch.dict(
            "os.environ",
            {"NEO4J_USER": "alias", "NEO4J_USERNAME": "explicit"},
            clear=True,
        ):
            self.assertEqual(Settings.from_env().neo4j_username, "explicit")

    def test_anthropic_output_audited_before_validation(self):
        import httpx
        from evidence_pipeline.extraction.providers import StructuredProvider
        from evidence_pipeline.extraction.service import Extractor
        from evidence_pipeline.state import State

        body = {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "name": "record_pico", "input": self.wire}
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        client = httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        )
        provider = StructuredProvider(
            "anthropic", "test-model", "not-a-key", client=client
        )
        state = State(":memory:")
        try:
            _, envelope = Extractor(provider, state).extract(self.sources)
            self.assertEqual(envelope.extraction.model_dump(), self.dto)
            self.assertEqual(len(state.all("provider_output")), 1)
            self.assertEqual(
                state.all("provider_output")[0]["transport"]["payload"], self.wire
            )
        finally:
            client.close()
            state.close()

    def test_enum_and_numeric_validation_not_bypassed(self):
        from pydantic import ValidationError

        next(x for x in self.wire["pico"] if x["name"] == "study_design")["text"] = (
            "invented_design"
        )
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(hydrate(self.wire, SCHEMA, self.sources))

    def test_explicit_dotenv_overrides_stale_process_value(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("NEO4J_USER=neo4j\nANTHROPIC_API_KEY= new-test-key\n")
            with patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "stale-test-key"}, clear=True
            ):
                settings = Settings.from_env(path)
                self.assertEqual(settings.api_key, "new-test-key")
                self.assertEqual(settings.neo4j_username, "neo4j")

    def test_iqr_cannot_be_labeled_a_confidence_interval(self):
        from pydantic import ValidationError
        from evidence_pipeline.schemas.pico import Interval

        quote = "IQR 2 to 4"
        span = dict(
            source_id="test",
            section="results",
            start=0,
            end=len(quote),
            quote=quote,
            page=None,
            table_or_figure=None,
            row=None,
            column=None,
        )

        def reported(value):
            return dict(
                value=value,
                raw=str(value) if isinstance(value, str) else str(int(value)),
                missing_reason=None,
                evidence=[span],
                extraction_confidence=0.9,
            )

        with self.assertRaisesRegex(ValidationError, "interquartile range"):
            Interval.model_validate(
                dict(
                    kind="confidence",
                    lower=reported(2.0),
                    upper=reported(4.0),
                    level_percent=dict(
                        value=None,
                        raw=None,
                        missing_reason="not_reported",
                        evidence=[],
                        extraction_confidence=None,
                    ),
                    sidedness="two_sided",
                    method=reported("IQR"),
                )
            )

    def test_worker_respects_durable_activation_block(self):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from pathlib import Path
        from evidence_pipeline.state import State
        from evidence_pipeline.worker import check_activation

        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.sqlite3")
            state = State(path)
            state.put(
                "activation",
                "daily-worker",
                {"enabled": False, "reason": "neo4j_authentication_failed"},
            )
            state.close()
            with self.assertRaisesRegex(
                PipelineError, "daily_worker_activation_blocked"
            ):
                check_activation(SimpleNamespace(state_path=path))

    def test_schema_directed_empty_declarations(self):
        pop = next(o for o in self.wire["objects"] if o["kind"] == "Population")
        pop["not_reported"].append("parent_population_id")
        pop["empty_lists"] = [
            x for x in pop["empty_lists"] if x != "exclusion_criteria"
        ]
        pop["not_reported"].append("exclusion_criteria")
        result = hydrate(self.wire, SCHEMA, self.sources)
        self.assertIsNone(result["populations"][0]["parent_population_id"])
        self.assertEqual(result["populations"][0]["exclusion_criteria"], [])
        PICOExtraction.model_validate(result)

    def test_empty_declaration_cannot_replace_a_present_value(self):
        pop = next(o for o in self.wire["objects"] if o["kind"] == "Population")
        pop["not_reported"].append("label")
        with self.assertRaisesRegex(PipelineError, "conflicting_transport_field"):
            hydrate(self.wire, SCHEMA, self.sources)

    def test_bounded_repair_retains_both_requests_and_revalidates(self):
        import httpx
        from evidence_pipeline.extraction.providers import StructuredProvider
        from evidence_pipeline.extraction.service import Extractor
        from evidence_pipeline.state import State

        pop = next(o for o in self.wire["objects"] if o["kind"] == "Population")
        key = pop["key"]
        original = next(f for f in pop["fields"] if f["name"] == "label")
        pop["fields"] = [f for f in pop["fields"] if f["name"] != "label"]
        requests = []

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            name = body["tools"][0]["name"]
            payload = (
                self.wire
                if name == "record_pico"
                else {
                    "field_fixes": [
                        {
                            "object_kind": "Population",
                            "object_key": key,
                            "field": original,
                        }
                    ],
                    "facts": [],
                    "passages": [],
                }
            )
            return httpx.Response(
                200,
                headers={"request-id": str(len(requests))},
                json={
                    "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "name": name, "input": payload}],
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handle))
        state = State(":memory:")
        try:
            service = Extractor(
                StructuredProvider(
                    "anthropic", "test-model", "fake-key", client=client
                ),
                state,
            )
            with self.assertRaises(PipelineError):
                service.extract(self.sources)
            _, envelope = service.extract(self.sources)
            self.assertEqual(envelope.extraction.model_dump(), self.dto)
            self.assertEqual(
                [r["tools"][0]["name"] for r in requests],
                ["record_pico", "repair_pico"],
            )
            self.assertEqual(len(state.all("provider_output")), 2)
            self.assertIn("repair-v3", envelope.prompt_version)
        finally:
            state.close()
            client.close()

    def test_cardinal_transcription_is_literal_and_preserves_exact_count(self):
        from evidence_pipeline.schemas.numeric_tokens import (
            parse_count_token,
            verbatim_numeric_token,
        )

        self.assertEqual(
            verbatim_numeric_token("24", ["Twenty-four patients received treatment."]),
            "Twenty-four",
        )
        self.assertEqual(parse_count_token("Twenty-four"), 24)
        self.assertEqual(parse_count_token("9007199254740993"), 9007199254740993)
        self.assertEqual(
            verbatim_numeric_token("24", ["Thirty patients received treatment."]), "24"
        )

    def test_cardinal_transcription_rejects_unsupported_contexts(self):
        from evidence_pipeline.schemas.numeric_tokens import verbatim_numeric_token

        for quote in [
            "minus twenty-four",
            "negative twenty-four",
            "− twenty-four",
            "twenty-four hundred",
            "one hundred and twenty-four",
            "twenty-four point five",
        ]:
            self.assertEqual(verbatim_numeric_token("24", [quote]), "24", quote)

    def test_closure_uses_only_explicit_references_to_existing_records(self):
        exposure = next(o for o in self.wire["objects"] if o["kind"] == "Exposure")
        root = next(f for f in self.wire["pico"] if f["name"] == "exposures")
        root["items"].remove(exposure["key"])
        result = hydrate(self.wire, SCHEMA, self.sources)
        PICOExtraction.model_validate(result)
        self.assertEqual(
            {e["id"] for e in result["exposures"]},
            {e["id"] for e in self.dto["exposures"]},
        )

    def test_null_reported_wire_cell_remains_unknown_not_zero(self):
        pop = next(o for o in self.wire["objects"] if o["kind"] == "Population")
        label = next(f for f in pop["fields"] if f["name"] == "label")
        label.update(kind="null", text="", items=[])
        result = hydrate(self.wire, SCHEMA, self.sources)
        self.assertEqual(
            result["populations"][0]["label"],
            dict(
                value=None,
                raw=None,
                evidence=[],
                missing_reason="not_reported",
                extraction_confidence=None,
            ),
        )
