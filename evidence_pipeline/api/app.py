"""Authenticated internal FastAPI boundary; not a public patient-data endpoint."""

import hmac
import json
import re
from uuid import uuid4
from typing import Annotated
from fastapi import FastAPI, Header, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator, field_validator
from ..config import Settings
from ..common import PipelineError
from ..state import State
from ..schemas.pico import StrictModel, SourceDocument, ExtractionEnvelope
from ..extraction.service import Extractor, SCHEMA
from ..extraction.providers import StructuredProvider
from ..graph.ingestion import Neo4jIngestor, EntityBinding


class SourceBatch(StrictModel):
    sources: Annotated[list[SourceDocument], Field(min_length=1, max_length=3)]

    @field_validator("sources", mode="before")
    @classmethod
    def parse_json_dates(cls, value):
        if isinstance(value, list):
            return [
                SourceDocument.model_validate_json(json.dumps(v))
                if isinstance(v, dict)
                else v
                for v in value
            ]
        return value

    @model_validator(mode="after")
    def bounded(self):
        if sum(len(s.text) for s in self.sources) > 60000:
            raise ValueError("Source limit exceeded")
        return self


class IngestRequest(StrictModel):
    extraction_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    bindings: Annotated[list[EntityBinding], Field(max_length=200)]


class BodyLimit:
    def __init__(self, app, maximum=1024 * 1024):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            size += len(data)
            if size > self.maximum:
                return await JSONResponse(
                    {"error": "request_too_large"}, status_code=413
                )(scope, receive, send)
            chunks.append(data)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": b"".join(chunks),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings=None, provider_factory=StructuredProvider, graph_factory=None):
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Clarity PICO Pipeline",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(BodyLimit)

    def authorized(authorization: Annotated[str | None, Header()] = None):
        if not settings.api_token:
            raise HTTPException(503, "pipeline_api_not_configured")
        value = authorization or ""
        if not value.startswith("Bearer ") or not hmac.compare_digest(
            value[7:], settings.api_token
        ):
            raise HTTPException(
                401, "unauthorized", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error": "invalid_request",
                "fields": [
                    {"location": e["loc"], "type": e["type"]} for e in error.errors()
                ],
            },
            status_code=422,
        )

    @app.exception_handler(PipelineError)
    async def pipeline_error(request, error):
        return JSONResponse({"error": str(error)}, status_code=422)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "pico-pipeline",
            "graph_configured": bool(settings.neo4j_uri),
            "publication": "reported_extracts_only",
        }

    @app.get("/v1/schema", dependencies=[Depends(authorized)])
    def schema():
        return SCHEMA

    @app.post("/v1/extractions", dependencies=[Depends(authorized)])
    def extract(body: SourceBatch):
        state = State(settings.state_path)
        provider = None
        owner = str(uuid4())
        locked = False
        try:
            state.acquire("pipeline", owner)
            locked = True
            provider = provider_factory(
                settings.provider, settings.model, settings.api_key
            )
            key, env = Extractor(provider, state, settings.daily_calls).extract(
                body.sources, owner
            )
            return {"extraction_key": key, "envelope": env.model_dump(mode="json")}
        finally:
            if provider:
                provider.close()
            if locked:
                state.release("pipeline", owner)
            state.close()

    @app.get("/v1/extractions/{key}", dependencies=[Depends(authorized)])
    def get_extraction(key: str):
        if not re.fullmatch("[a-f0-9]{64}", key):
            raise HTTPException(404, "not_found")
        state = State(settings.state_path)
        try:
            value = state.get("extraction", key)
            if not value:
                raise HTTPException(404, "not_found")
            return value
        finally:
            state.close()

    @app.post("/v1/ingestions", dependencies=[Depends(authorized)])
    def ingest(body: IngestRequest):
        state = State(settings.state_path)
        driver = None
        try:
            value = state.get("extraction", body.extraction_key)
            if not value:
                raise HTTPException(404, "extraction_not_found")
            env = ExtractionEnvelope.model_validate_json(json.dumps(value["envelope"]))
            if graph_factory:
                sink = graph_factory()
            else:
                driver = settings.graph()
                sink = Neo4jIngestor(driver, settings.neo4j_database)
            result = sink.ingest(env, body.bindings)
            state.put(
                "ingestion",
                body.extraction_key,
                {"extraction_key": body.extraction_key, **result},
            )
            return result
        finally:
            if driver:
                driver.close()
            state.close()

    return app


app = create_app()
