from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from ..common import digest, now, PipelineError
from ..schemas.pico import PICOExtraction, ExtractionEnvelope, SourceDocument
from .transport import VERSION as TRANSPORT_VERSION
from .providers import ProviderOutput
from .repair import structural_issues, apply_repair
from .grounding import ground_transport, VERSION as GROUNDING_VERSION

INSTRUCTIONS = Path(__file__).with_name("INSTRUCTIONS.md").read_text()
PROMPT_VERSION = TRANSPORT_VERSION + ":" + digest(INSTRUCTIONS)[:16]
SCHEMA = PICOExtraction.model_json_schema()
SCHEMA_HASH = digest(SCHEMA)


class Extractor:
    cache_version = SCHEMA_HASH + PROMPT_VERSION

    def __init__(self, provider, state, daily_calls=20, max_source_chars=60000):
        self.provider = provider
        self.format_version = getattr(provider, "format_version", "")
        self.cache_version = type(self).cache_version + self.format_version
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
                **({"format": self.format_version} if self.format_version else {}),
            }
        )
        cached = self.state.get("extraction", key)
        if cached:
            return key, ExtractionEnvelope.model_validate_json(
                __import__("json").dumps(cached["envelope"])
            )
        if self.format_version and hasattr(self.provider, "decode_payload"):
            for prior in sorted(
                self.state.all("attempt"), key=lambda a: a["at"], reverse=True
            ):
                if prior.get("cache_key") != key or prior.get("status") != "failed":
                    continue
                raw = self.state.get("provider_output", prior["id"])
                if not raw or raw.get("raw_payload") is None:
                    continue
                try:
                    dto = self.provider.decode_payload(raw["raw_payload"], sources)
                    restored = ExtractionEnvelope(
                        run_id=run_id or str(uuid4()),
                        extracted_at=now(),
                        provider=self.provider.name,
                        model=self.provider.model,
                        prompt_version=PROMPT_VERSION + ":" + self.format_version,
                        schema_sha256=SCHEMA_HASH,
                        request_id=raw["request_id"],
                        sources=sources,
                        extraction=PICOExtraction.model_validate(dto),
                    )
                except (PipelineError, ValueError, TypeError, KeyError):
                    break
                self.state.put(
                    "extraction",
                    key,
                    {
                        "id": key,
                        "envelope": restored.model_dump(mode="json"),
                        "revalidated_from": prior["id"],
                        "grounding": {
                            "version": self.format_version,
                            "excluded": getattr(self.provider, "decode_audit", []),
                        },
                    },
                )
                return key, restored
        previous_attempt = previous_output = None
        recovery_issues = []
        if self.provider.name == "anthropic" and getattr(
            self.provider, "supports_repairs", False
        ):
            for attempt in sorted(
                self.state.all("attempt"), key=lambda a: a["at"], reverse=True
            ):
                if attempt.get("cache_key") == key and attempt["status"] == "failed":
                    saved = self.state.get("provider_output", attempt["id"])
                    if saved and saved.get("transport"):
                        previous_attempt, previous_output = attempt, saved
                        break
            if previous_output:
                # Revalidate saved bytes after decoder fixes without another API call.
                # Preserve the failed attempt; acceptance is a separate audit event.
                try:
                    grounded, excluded = ground_transport(
                        previous_output["payload"], SCHEMA, sources
                    )
                    restored = ExtractionEnvelope(
                        run_id=run_id or str(uuid4()),
                        extracted_at=now(),
                        provider=self.provider.name,
                        model=self.provider.model,
                        prompt_version=PROMPT_VERSION
                        + (":" + self.format_version if self.format_version else "")
                        + (
                            ":" + previous_output["transport"]["repair_version"]
                            if previous_output["transport"].get("repair_version")
                            else ""
                        ),
                        schema_sha256=SCHEMA_HASH,
                        request_id=previous_output["request_id"],
                        sources=sources,
                        extraction=grounded,
                    )
                except (PipelineError, ValueError, TypeError, KeyError) as error:
                    recovery_issues = getattr(error, "validation_issues", [])
                else:
                    self.state.put(
                        "extraction",
                        key,
                        {
                            "id": key,
                            "envelope": restored.model_dump(mode="json"),
                            "revalidated_from": previous_attempt["id"],
                            "decoder": "schema-directed-absence-v1",
                            "grounding": {
                                "version": GROUNDING_VERSION,
                                "excluded": excluded,
                            },
                        },
                    )
                    return key, restored
            if (
                previous_output
                and previous_output["transport"].get("repair_depth", 0) >= 2
            ):
                raise PipelineError("extraction_repair_limit_reached")
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
            if previous_output:
                previous = ProviderOutput(
                    previous_output["payload"],
                    previous_output["request_id"],
                    previous_output["input_tokens"],
                    previous_output["output_tokens"],
                    previous_output["transport"],
                )
                issues = (
                    structural_issues(previous.payload, SCHEMA)
                    + previous_attempt.get("validation_errors", [])
                    + recovery_issues
                )
                issues.append({"code": previous_attempt["code"]})
                output = self.provider.repair(
                    INSTRUCTIONS, sources, SCHEMA, previous, issues
                )
                output.transport["repair_depth"] = (
                    previous.transport.get("repair_depth", 0) + 1
                )
                output.transport["previous_attempt_id"] = previous_attempt["id"]
            else:
                output = self.provider.extract(INSTRUCTIONS, sources, SCHEMA)
            # Preserve provider bytes as structured transport for replay and audit,
            # even when the final approved PICO/source validators reject them.
            self.state.put(
                "provider_output",
                attempt_id,
                {
                    "id": attempt_id,
                    "request_id": output.request_id,
                    "payload": output.payload,
                    "raw_payload": output.raw_payload,
                    "transport": output.transport,
                    "input_tokens": output.input_tokens,
                    "output_tokens": output.output_tokens,
                },
            )
            transport_payload = output.payload
            if output.transport and output.transport.get("repair_version"):
                repaired = apply_repair(output.payload, output.transport["patch"])
                stored = self.state.get("provider_output", attempt_id)
                stored["base_payload"] = output.payload
                stored["payload"] = repaired
                self.state.put("provider_output", attempt_id, stored)
                transport_payload = repaired
            if output.transport:
                extraction, excluded = ground_transport(
                    transport_payload, SCHEMA, sources
                )
            else:
                if hasattr(self.provider, "decode_payload"):
                    transport_payload = self.provider.decode_payload(
                        transport_payload, sources
                    )
                extraction, excluded = (
                    PICOExtraction.model_validate(transport_payload),
                    getattr(self.provider, "decode_audit", []),
                )
            envelope = ExtractionEnvelope(
                run_id=run_id or str(uuid4()),
                extracted_at=now(),
                provider=self.provider.name,
                model=self.provider.model,
                prompt_version=PROMPT_VERSION
                + (":" + self.format_version if self.format_version else "")
                + (
                    ":" + output.transport["repair_version"]
                    if output.transport and output.transport.get("repair_version")
                    else ""
                ),
                schema_sha256=SCHEMA_HASH,
                request_id=output.request_id,
                sources=sources,
                extraction=extraction,
            )
            with self.state.transaction():
                self.state.put(
                    "extraction",
                    key,
                    {
                        "id": key,
                        "envelope": envelope.model_dump(mode="json"),
                        "source_attempt_id": attempt_id,
                        "grounding": {
                            "version": GROUNDING_VERSION,
                            "excluded": excluded,
                        },
                    },
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
                    "validation_errors": [
                        {"loc": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                        for e in error.errors(include_input=False, include_url=False)
                    ]
                    if isinstance(error, ValidationError)
                    else getattr(error, "validation_issues", []),
                },
            )
            raise PipelineError(code) from None
