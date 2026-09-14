from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from ..common import digest, now, PipelineError
from ..schemas.pico import PICOExtraction, ExtractionEnvelope, SourceDocument

INSTRUCTIONS = Path(__file__).with_name("INSTRUCTIONS.md").read_text()
PROMPT_VERSION = "pico-source-only-v1:" + digest(INSTRUCTIONS)[:16]
SCHEMA = PICOExtraction.model_json_schema()
SCHEMA_HASH = digest(SCHEMA)


class Extractor:
    cache_version = SCHEMA_HASH + PROMPT_VERSION

    def __init__(self, provider, state, daily_calls=20, max_source_chars=60000):
        self.provider = provider
        self.state = state
        self.daily_calls = daily_calls
        self.max_source_chars = max_source_chars

    def extract(self, sources, run_id=None):
        # Revalidate even already-instantiated models; model_construct is not a bypass.
        sources = [
            SourceDocument.model_validate_json(s.model_dump_json()) for s in sources
        ]
        if not sources or len({s.id for s in sources}) != len(sources):
            raise PipelineError("invalid_source_set")
        if sum(len(s.text) for s in sources) > self.max_source_chars:
            raise PipelineError("source_size_exceeds_extraction_limit")
        key = digest(
            {
                "sources": sorted(
                    (s.id, s.sha256, s.version, s.kind, s.pmid, s.pmcid, s.doi)
                    for s in sources
                ),
                "provider": self.provider.name,
                "model": self.provider.model,
                "prompt": PROMPT_VERSION,
                "schema": SCHEMA_HASH,
            }
        )
        cached = self.state.get("extraction", key)
        if cached:
            return key, ExtractionEnvelope.model_validate_json(
                __import__("json").dumps(cached["envelope"])
            )
        self.state.reserve_call(now().date().isoformat(), self.daily_calls)
        attempt_id = str(uuid4())
        self.state.put(
            "attempt",
            attempt_id,
            {
                "id": attempt_id,
                "cache_key": key,
                "status": "started",
                "at": now().isoformat(),
            },
        )
        try:
            output = self.provider.extract(INSTRUCTIONS, sources, SCHEMA)
            extraction = PICOExtraction.model_validate(output.payload)
            envelope = ExtractionEnvelope(
                run_id=run_id or str(uuid4()),
                extracted_at=now(),
                provider=self.provider.name,
                model=self.provider.model,
                prompt_version=PROMPT_VERSION,
                schema_sha256=SCHEMA_HASH,
                request_id=output.request_id,
                sources=sources,
                extraction=extraction,
            )
            with self.state.transaction():
                self.state.put(
                    "extraction",
                    key,
                    {"id": key, "envelope": envelope.model_dump(mode="json")},
                )
                self.state.put(
                    "attempt",
                    attempt_id,
                    {
                        "id": attempt_id,
                        "cache_key": key,
                        "status": "validated",
                        "at": now().isoformat(),
                        "request_id": output.request_id,
                        "input_tokens": output.input_tokens,
                        "output_tokens": output.output_tokens,
                    },
                )
            return key, envelope
        except (ValidationError, ValueError, PipelineError) as error:
            code = (
                str(error)
                if isinstance(error, PipelineError)
                else "extraction_schema_or_source_validation_failed"
            )
            self.state.put(
                "attempt",
                attempt_id,
                {
                    "id": attempt_id,
                    "cache_key": key,
                    "status": "failed",
                    "code": code,
                    "at": now().isoformat(),
                },
            )
            raise PipelineError(code) from None
