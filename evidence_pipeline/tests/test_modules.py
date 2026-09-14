import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from evidence_pipeline.common import PipelineError
from evidence_pipeline.state import State
from evidence_pipeline.retrieval.europe_pmc import (
    EuropePMC,
    Target,
    query_for,
    document_from,
)
from evidence_pipeline.extraction.providers import (
    StructuredProvider,
    ProviderOutput,
)
from evidence_pipeline.extraction.service import Extractor, SCHEMA, SCHEMA_HASH
from evidence_pipeline.graph.ingestion import Neo4jIngestor, EntityBinding, prepare
from evidence_pipeline.schemas.pico import (
    SourceDocument,
    ExtractionEnvelope,
    PICOExtraction,
)
from evidence_pipeline.config import Settings
from evidence_pipeline.runner import Pipeline
from evidence_pipeline.api.app import create_app
from evidence_pipeline.tests.fixtures import fixture, source


def record(pmid="12345678"):
    return {
        "id": pmid,
        "pmid": pmid,
        "source": "MED",
        "title": "Example trial",
        "abstractText": "<p>Adults received Drug A.</p>",
        "pubTypeList": {"pubType": ["Randomized Controlled Trial"]},
    }


class StubProvider:
    name = "anthropic"
    model = "test-model"

    def __init__(self, *args, payload=None):
        self.calls = 0
        self.payload = payload or fixture()

    def extract(self, *args):
        self.calls += 1
        return ProviderOutput(deepcopy(self.payload), "request-test", 10, 20)

    def close(self):
        pass


def envelope():
    s = source()
    s["id"] = "pmid:12345678"
    s["pmid"] = "12345678"
    payload = fixture()

    def patch(x):
        if isinstance(x, dict):
            if x.get("source_id") == "fixture:1":
                x["source_id"] = "pmid:12345678"
            for v in x.values():
                patch(v)
        elif isinstance(x, list):
            for v in x:
                patch(v)

    patch(payload)
    return ExtractionEnvelope(
        run_id="run1",
        extracted_at=s["retrieved_at"],
        provider="anthropic",
        model="test",
        prompt_version="test",
        schema_sha256=SCHEMA_HASH,
        request_id=None,
        sources=[SourceDocument.model_validate(s)],
        extraction=PICOExtraction.model_validate(payload),
    )


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.state = State(":memory:")
        self.target = Target(id="drug-a", terms=["Drug A"])

    def tearDown(self):
        self.state.close()

    def test_query_quotes_terms_and_bounds(self):
        q = query_for(
            Target(id="t", terms=['a" OR *:*']), date(2026, 1, 1), date(2026, 1, 2)
        )
        self.assertIn('a\\" OR *:*', q)
        self.assertIn("FIRST_IDATE:[2026-01-01 TO 2026-01-02]", q)
        with self.assertRaises(ValueError):
            query_for(self.target, date(2026, 2, 1), date(2026, 1, 1))

    def test_pagination_dedup_and_cached_window(self):
        calls = []

        def handle(request):
            cursor = request.url.params["cursorMark"]
            calls.append(cursor)
            return httpx.Response(
                200,
                json={
                    "hitCount": 2,
                    "nextCursorMark": "next" if cursor == "*" else "end",
                    "resultList": {"result": [record("1" if cursor == "*" else "2")]},
                },
            )

        api = EuropePMC(
            httpx.Client(transport=httpx.MockTransport(handle)), page_size=1
        )
        window = api.retrieve(
            self.target, date(2026, 1, 1), date(2026, 1, 2), self.state
        )
        self.assertTrue(window["complete"])
        self.assertEqual(len(self.state.all("candidate")), 2)
        api.retrieve(self.target, date(2026, 1, 1), date(2026, 1, 2), self.state)
        self.assertEqual(calls, ["*", "next"])

    def test_partial_window_resumes_without_advancing_failed_cursor(self):
        def handle(request):
            if request.url.params["cursorMark"] == "*":
                return httpx.Response(
                    200,
                    json={
                        "hitCount": 2,
                        "nextCursorMark": "next",
                        "resultList": {"result": [record("1")]},
                    },
                )
            return httpx.Response(503)

        api = EuropePMC(
            httpx.Client(transport=httpx.MockTransport(handle)), sleep=lambda _: None
        )
        with self.assertRaises(PipelineError):
            api.retrieve(self.target, date(2026, 1, 1), date(2026, 1, 2), self.state)
        window = self.state.all("window")[0]
        self.assertFalse(window["complete"])
        self.assertEqual(window["cursor"], "next")
        seen = []

        def succeed(request):
            seen.append(request.url.params["cursorMark"])
            return httpx.Response(
                200,
                json={
                    "hitCount": 2,
                    "nextCursorMark": "end",
                    "resultList": {"result": [record("2")]},
                },
            )

        api.client = httpx.Client(transport=httpx.MockTransport(succeed))
        self.assertTrue(
            api.retrieve(self.target, date(2026, 1, 1), date(2026, 1, 2), self.state)[
                "complete"
            ]
        )
        self.assertEqual(seen, ["next"])

    def test_stalled_cursor_never_completes(self):
        api = EuropePMC(
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200,
                        json={
                            "hitCount": 2,
                            "nextCursorMark": "*",
                            "resultList": {"result": [record()]},
                        },
                    )
                )
            )
        )
        with self.assertRaises(PipelineError):
            api.retrieve(self.target, date(2026, 1, 1), date(2026, 1, 2), self.state)
        self.assertEqual(self.state.all("window"), [])

    def test_missing_abstract_and_retraction_are_not_extracted(self):
        r = record()
        r.pop("abstractText")
        self.assertEqual(document_from(r)[2], "abstract_unavailable")
        r = record()
        r["isRetracted"] = "Y"
        self.assertEqual(document_from(r)[2], "source_retraction_notice")

    def test_atomic_state_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.state.transaction():
                self.state.put("test", "1", {"x": 1})
                raise RuntimeError()
        self.assertIsNone(self.state.get("test", "1"))


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.state = State(":memory:")
        self.source = SourceDocument.model_validate(source())

    def tearDown(self):
        self.state.close()

    def test_cache_reuses_model_call_and_revalidates(self):
        p = StubProvider()
        extractor = Extractor(p, self.state)
        key, a = extractor.extract([self.source])
        other, b = extractor.extract([self.source])
        self.assertEqual(key, other)
        self.assertEqual(p.calls, 1)
        self.assertEqual(a, b)

    def test_invalid_output_never_cached(self):
        payload = fixture()
        payload["summary"] = "forbidden"
        with self.assertRaises(PipelineError):
            Extractor(StubProvider(payload=payload), self.state).extract([self.source])
        self.assertEqual(self.state.all("extraction"), [])
        self.assertEqual(self.state.all("attempt")[0]["status"], "failed")

    def test_daily_call_budget_enforced_before_provider(self):
        self.state.reserve_call("2026-01-01", 1)
        with self.assertRaises(PipelineError):
            self.state.reserve_call("2026-01-01", 1)

    def test_provider_model_changes_invalidate_cache(self):
        p = StubProvider()
        extractor = Extractor(p, self.state)
        a, _ = extractor.extract([self.source])
        p.model = "changed"
        b, _ = extractor.extract([self.source])
        self.assertNotEqual(a, b)
        self.assertEqual(p.calls, 2)

    def test_openai_schema_and_truncation_handling(self):
        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "length", "message": {"content": "{}"}}
                    ]
                },
            )

        p = StructuredProvider(
            "openai",
            "configured-model",
            "not-a-key",
            httpx.Client(transport=httpx.MockTransport(handle)),
        )
        with self.assertRaises(PipelineError):
            p.extract("JSON only", [self.source], SCHEMA)
        self.assertTrue(bodies[0]["response_format"]["json_schema"]["strict"])
        self.assertFalse(bodies[0]["store"])

    def test_anthropic_tool_has_strict_schema_and_rejects_prose(self):
        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "stop_reason": "tool_use",
                    "content": [
                        {"type": "text", "text": "summary"},
                        {"type": "tool_use", "name": "record_pico", "input": fixture()},
                    ],
                },
            )

        p = StructuredProvider(
            "anthropic",
            "configured-model",
            "not-a-key",
            httpx.Client(transport=httpx.MockTransport(handle)),
        )
        with self.assertRaises(PipelineError):
            p.extract("JSON only", [self.source], SCHEMA)
        self.assertTrue(bodies[0]["tools"][0]["strict"])

    def test_provider_failure_does_not_expose_response_or_key(self):
        p = StructuredProvider(
            "anthropic",
            "configured-model",
            "secret-value",
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(401, json={"error": "secret-value"})
                )
            ),
        )
        with self.assertRaisesRegex(PipelineError, "^extraction_provider_http_401$"):
            p.extract("JSON only", [self.source], SCHEMA)


class Result:
    def __init__(self, value=None):
        self.value = value

    def single(self):
        return self.value

    def consume(self):
        return None


class Transaction:
    def __init__(self, found=1, existing=None):
        self.queries = []
        self.found = found
        self.existing = existing or []

    def run(self, q, **params):
        self.queries.append((q, params))
        if "RETURN count(n)" in q:
            return Result({"count": self.found})
        if "collect(DISTINCT s.id)" in q:
            return Result({"ids": self.existing})
        return Result()


class GraphTests(unittest.TestCase):
    def test_projection_is_parameterized_and_source_linked(self):
        env = envelope()
        binding = EntityBinding(
            local_id="e1",
            kind="Intervention",
            node_id="existing-drug",
            reported_name="Drug A",
        )
        env, id, study, aliases = prepare(env, [binding])
        tx = Transaction()
        result = Neo4jIngestor._write(tx, env, id, study, aliases, [binding])
        self.assertEqual(result["results"], 1)
        queries = "\n".join(q for q, _ in tx.queries)
        self.assertIn("SUPPORTED_BY", queries)
        self.assertIn("MEASURES", queries)
        self.assertNotIn("IMPROVES", queries)
        self.assertNotIn("CONFLICTS_WITH", queries)
        self.assertNotIn("Drug A", queries)
        self.assertTrue(any(p.get("quote") for _, p in tx.queries))

    def test_missing_existing_entity_aborts_before_write(self):
        env = envelope()
        b = EntityBinding(
            local_id="e1",
            kind="Intervention",
            node_id="missing",
            reported_name="Drug A",
        )
        env, id, s, a = prepare(env, [b])
        tx = Transaction(found=0)
        with self.assertRaises(PipelineError):
            Neo4jIngestor._write(tx, env, id, s, a, [b])
        self.assertEqual(len(tx.queries), 1)

    def test_identity_collision_aborts(self):
        env, id, s, a = prepare(envelope(), [])
        with self.assertRaises(PipelineError):
            Neo4jIngestor._write(
                Transaction(existing=["pmid:1", "doi:other"]), env, id, s, a, []
            )

    def test_hash_is_independent_of_retry_run_id(self):
        env = envelope()
        id = prepare(env, [])[1]
        env.run_id = "retry"
        self.assertEqual(prepare(env, [])[1], id)

    def test_binding_cannot_invent_an_entity_name(self):
        b = EntityBinding(
            local_id="e1",
            kind="Intervention",
            node_id="x",
            reported_name="Unreported drug",
        )
        with self.assertRaises(PipelineError):
            prepare(envelope(), [b])


class APITests(unittest.TestCase):
    def test_auth_validation_and_cached_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                str(Path(directory) / "state.sqlite3"),
                "anthropic",
                "test",
                "key",
                "",
                "",
                "",
                "neo4j",
                "token",
                5,
                2,
            )
            app = create_app(settings, provider_factory=StubProvider)
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/v1/schema").status_code, 401)
                headers = {"Authorization": "Bearer token"}
                self.assertEqual(
                    client.get("/v1/schema", headers=headers).status_code, 200
                )
                body = {
                    "sources": [
                        SourceDocument.model_validate(source()).model_dump(mode="json")
                    ]
                }
                response = client.post("/v1/extractions", headers=headers, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                key = response.json()["extraction_key"]
                self.assertEqual(
                    client.get("/v1/extractions/" + key, headers=headers).status_code,
                    200,
                )
                response = client.post(
                    "/v1/extractions",
                    headers=headers,
                    json={"sources": "private-input"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("private-input", response.text)
                self.assertEqual(
                    client.post(
                        "/v1/extractions",
                        headers=headers,
                        content="x" * (1024 * 1024 + 1),
                    ).status_code,
                    413,
                )


class RunnerTests(unittest.TestCase):
    def test_validated_extraction_survives_graph_failure_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(str(Path(directory) / "s.db"))
            doc = SourceDocument.model_validate(source()).model_dump(mode="json")
            state.put(
                "candidate",
                "candidate",
                {
                    "id": "candidate",
                    "study_id": "fixture:1",
                    "target_ids": ["t"],
                    "document": doc,
                },
            )

            class Retriever:
                def retrieve(self, *args):
                    return {"id": "w", "complete": True}

            class Graph:
                calls = 0

                def ingest(self, *args):
                    self.calls += 1
                    if self.calls == 1:
                        raise PipelineError("graph_temporarily_unavailable")
                    return {"study_id": "test", "extraction_id": "test"}

            provider = StubProvider()
            graph = Graph()
            pipeline = Pipeline(
                state, Retriever(), Extractor(provider, state), graph, max_calls=1
            )
            target = Target(id="t", terms=["Drug A"])
            first = pipeline.run([target], date(2026, 1, 1), date(2026, 1, 2))
            self.assertEqual(first["status"], "partial_failure")
            self.assertEqual(provider.calls, 1)
            second = pipeline.run([target], date(2026, 1, 1), date(2026, 1, 2))
            self.assertEqual(second["status"], "completed")
            self.assertEqual(second["ingestions"], 1)
            self.assertEqual(provider.calls, 1)
            third = pipeline.run([target], date(2026, 1, 1), date(2026, 1, 2))
            self.assertEqual(third["ingestions"], 0)
            state.close()

    def test_lease_prevents_competing_workers(self):
        state = State(":memory:")
        state.acquire("pipeline", "first")
        with self.assertRaises(PipelineError):
            state.acquire("pipeline", "second")
        state.release("pipeline", "first")
        state.acquire("pipeline", "second")
        state.close()

    def test_search_failure_does_not_advance_checkpoint(self):
        from evidence_pipeline.common import digest

        state = State(":memory:")
        target = Target(id="t", terms=["Drug A"])
        scope = digest(target.model_dump())
        state.put("checkpoint", scope, {"until": "2026-01-01"})

        class Broken:
            def retrieve(self, *args):
                raise PipelineError("retrieval_retry_exhausted")

        run = Pipeline(state, Broken()).run(
            [target], until=date(2026, 1, 7), retrieval_only=True
        )
        self.assertEqual(run["status"], "partial_failure")
        self.assertEqual(state.get("checkpoint", scope)["until"], "2026-01-01")
        state.close()

    def test_existing_only_never_queries_retrieval(self):
        class Forbidden:
            def retrieve(self, *args):
                raise AssertionError("Unexpected retrieval")

        state = State(":memory:")
        try:
            result = Pipeline(state, Forbidden(), Extractor(StubProvider(), state)).run(
                [Target(id="t", terms=["Drug A"])], existing_only=True
            )
            self.assertEqual(result["windows"], [])
            self.assertEqual(result["status"], "completed")
        finally:
            state.close()

    def test_systemic_provider_failure_preserves_candidate_retries(self):
        class BrokenProvider(StubProvider):
            def extract(self, *args):
                self.calls += 1
                raise PipelineError("extraction_provider_http_401")

        state = State(":memory:")
        try:
            for ident in ("a", "b"):
                state.put(
                    "candidate",
                    ident,
                    {
                        "id": ident,
                        "target_ids": ["t"],
                        "document": SourceDocument.model_validate(source()).model_dump(
                            mode="json"
                        ),
                    },
                )
            provider = BrokenProvider()
            result = Pipeline(state, None, Extractor(provider, state), max_calls=3).run(
                [Target(id="t", terms=["Drug A"])], existing_only=True
            )
            self.assertEqual(provider.calls, 1)
            self.assertEqual(result["status"], "partial_failure")
            self.assertEqual(state.all("job")[0]["attempts"], 0)
            self.assertEqual(state.all("job")[0]["status"], "ready")
        finally:
            state.close()
