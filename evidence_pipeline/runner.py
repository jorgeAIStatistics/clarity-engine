"""Independently resumable retrieval/extraction/graph work, bounded per run."""

import json
from datetime import date, timedelta
from uuid import uuid4
from .common import digest, now, PipelineError
from .schemas.pico import SourceDocument
from .graph.ingestion import EntityBinding


def resolve_bindings(extraction, mapping):
    """Exact, operator-configured names only. Never fuzzy-match a graph ID."""
    bindings = []
    for e in extraction.exposures:
        kind = "Biomarker" if e.kind == "biomarker" else "Intervention"
        candidates = [
            m
            for m in mapping
            if m["kind"] == kind and m["reported_name"] == e.name.value
        ]
        for m in candidates:
            bindings.append(EntityBinding(local_id=e.id, **m))
    for p in extraction.populations:
        for c in p.conditions:
            for m in mapping:
                if m["kind"] == "Condition" and m["reported_name"] == c.value:
                    bindings.append(EntityBinding(local_id=p.id, **m))
    return bindings


class Pipeline:
    def __init__(self, state, retriever, extractor=None, graph=None, max_calls=3):
        self.state = state
        self.retriever = retriever
        self.extractor = extractor
        self.graph = graph
        self.max_calls = max_calls

    def run(
        self,
        targets,
        since=None,
        until=None,
        mapping=(),
        retrieval_only=False,
        existing_only=False,
    ):
        run_id = str(uuid4())
        until = until or date.today()
        calls = 0
        self.state.acquire("pipeline", run_id)
        run = {
            "id": run_id,
            "started_at": now().isoformat(),
            "windows": [],
            "extractions": 0,
            "ingestions": 0,
            "errors": [],
            "status": "running",
        }
        self.state.put("run", run_id, run)
        heartbeat = lambda: self.state.renew("pipeline", run_id)
        try:
            for target in [] if existing_only else targets:
                scope = digest(target.model_dump())
                checkpoint = self.state.get("checkpoint", scope)
                # Finish a partially retrieved fixed window before opening a new one.
                pending = next(
                    (
                        w
                        for w in self.state.all("window")
                        if w["target_id"] == target.id
                        and not w["complete"]
                        and w.get("target_scope") == scope
                    ),
                    None,
                )
                start = since or (
                    date.fromisoformat(checkpoint["until"]) - timedelta(days=2)
                    if checkpoint
                    else until - timedelta(days=30)
                )
                end = until
                if pending:
                    start = date.fromisoformat(pending["since"])
                    end = date.fromisoformat(pending["until"])
                try:
                    window = self.retriever.retrieve(
                        target, start, end, self.state, heartbeat
                    )
                    run["windows"].append(window["id"])
                    self.state.put(
                        "checkpoint",
                        scope,
                        {
                            "until": max(
                                end.isoformat(),
                                checkpoint["until"] if checkpoint else end.isoformat(),
                            )
                        },
                    )
                except PipelineError as e:
                    run["errors"].append(
                        {"stage": "retrieval", "target_id": target.id, "code": str(e)}
                    )
            if not retrieval_only:
                if self.extractor is None:
                    raise PipelineError("extractor_not_configured")
                for candidate in self.state.all("candidate"):
                    if (
                        not set(candidate["target_ids"]) & {t.id for t in targets}
                        or not candidate["document"]
                    ):
                        continue
                    heartbeat()
                    job_key = digest(
                        [
                            candidate["id"],
                            self.extractor.provider.name,
                            self.extractor.provider.model,
                            self.extractor.cache_version,
                        ]
                    )
                    job = self.state.get("job", job_key) or {
                        "id": job_key,
                        "candidate_id": candidate["id"],
                        "attempts": 0,
                        "status": "ready",
                    }
                    # Reuse a validated artifact for the same immutable document
                    # after model changes; a new source hash still needs extraction.
                    if not job.get("extraction_key"):
                        source = candidate["document"]
                        from .extraction.service import SCHEMA_HASH

                        cached = [
                            r
                            for r in self.state.all("extraction")
                            if r["envelope"].get("schema_sha256") == SCHEMA_HASH
                            and len(r["envelope"].get("sources", [])) == 1
                            and r["envelope"]["sources"][0]["id"] == source["id"]
                            and r["envelope"]["sources"][0]["sha256"]
                            == source["sha256"]
                        ]
                        if cached:
                            saved = max(
                                cached, key=lambda r: r["envelope"]["extracted_at"]
                            )
                            job.update(extraction_key=saved["id"], status="validated")
                    mapping_hash = digest(mapping)
                    if (
                        job["status"] == "ingested"
                        and job.get("mapping_hash") == mapping_hash
                    ):
                        continue
                    if (
                        job["attempts"] >= 3
                        and job["status"] == "failed"
                        and not job.get("extraction_key")
                    ):
                        continue
                    # Cached validated output can still be graphed when call budget is exhausted.
                    if not job.get("extraction_key") and calls >= self.max_calls:
                        continue
                    try:
                        if job.get("extraction_key"):
                            from .schemas.pico import ExtractionEnvelope

                            saved = self.state.get("extraction", job["extraction_key"])
                            env = ExtractionEnvelope.model_validate_json(
                                json.dumps(saved["envelope"])
                            )
                        else:
                            calls += 1
                            job["attempts"] += 1
                            self.state.put(
                                "job", job_key, {**job, "status": "extracting"}
                            )
                            key, env = self.extractor.extract(
                                [
                                    SourceDocument.model_validate_json(
                                        json.dumps(candidate["document"])
                                    )
                                ],
                                run_id,
                            )
                            # A suspended host may resume after its lease expired.
                            # The immutable extraction cache is safe to retain, but
                            # an expired owner must not publish jobs or graph writes.
                            heartbeat()
                            job.update(extraction_key=key, status="validated")
                            run["extractions"] += 1
                            self.state.put("job", job_key, job)
                        if self.graph:
                            heartbeat()
                            bindings = resolve_bindings(env.extraction, mapping)
                            result = self.graph.ingest(env, bindings)
                            job.update(
                                status="ingested",
                                graph=result,
                                mapping_hash=mapping_hash,
                            )
                            run["ingestions"] += 1
                        self.state.put("job", job_key, job)
                    except Exception as e:
                        code = (
                            str(e) if isinstance(e, PipelineError) else type(e).__name__
                        )
                        if code == "pipeline_lease_lost":
                            run["errors"].append({"stage": "lease", "code": code})
                            break
                        if code in {
                            "extraction_provider_http_400",
                            "extraction_provider_http_401",
                            "extraction_provider_http_403",
                            "extraction_provider_http_404",
                            "extraction_provider_http_429",
                        }:
                            # Configuration/rate-limit failures affect the whole run,
                            # not this paper. Do not burn every candidate's retries.
                            job.update(
                                status="ready",
                                attempts=max(0, job["attempts"] - 1),
                                code=code,
                            )
                            self.state.put("job", job_key, job)
                            run["errors"].append({"stage": "provider", "code": code})
                            break
                        if code == "daily_extraction_budget_exhausted":
                            job.update(
                                status="ready", attempts=max(0, job["attempts"] - 1)
                            )
                            self.state.put("job", job_key, job)
                            run["errors"].append({"stage": "budget", "code": code})
                            break
                        job.update(status="failed", code=code)
                        self.state.put("job", job_key, job)
                        run["errors"].append(
                            {
                                "stage": "extraction_or_graph",
                                "candidate_id": candidate["id"],
                                "code": code,
                            }
                        )
            run["status"] = "partial_failure" if run["errors"] else "completed"
            return run
        finally:
            if run["status"] == "running":
                run["status"] = "failed"
            run["finished_at"] = now().isoformat()
            run["extraction_attempts"] = calls
            self.state.put("run", run_id, run)
            self.state.release("pipeline", run_id)
