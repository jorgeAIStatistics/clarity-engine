# Clarity structured evidence pipeline

Phase 1 implemented: Europe PMC retrieval → structured PICO extraction → strict
source validation → Neo4j projection. The approved Pydantic contract is in
`schemas/pico.py`; the full JSON Schema is `schemas/pico.schema.json`.
This package is independent of the existing Flask service and live research
worker. It does not replace or deploy them automatically.

## Modules

| Module | Behavior |
| --- | --- |
| `retrieval/europe_pmc.py` | Target-intervention RCT/meta-analysis queries, core records, cursor pagination, retry/backoff, immutable source text, hashes, durable page checkpoints |
| `extraction/providers.py` | OpenAI strict JSON Schema and Anthropic strict tool input; refusal/truncation/prose rejection; explicit model and bounded token output |
| `extraction/service.py` | Approved Pydantic validation, exact-source verification, audit envelope, source/schema/prompt/model cache keys, durable attempts and daily call budget |
| `graph/ingestion.py` | Parameterized Cypher, managed atomic transaction, publication-alias resolution, versioned extractions, numeric result/interval/p-value nodes, exact source spans, explicit existing-entity bindings |
| `state.py` | SQLite WAL state, atomic source/cursor commits, durable jobs and call reservation, single-worker lease |
| `runner.py` | Incremental retrieval, bounded extraction, independent graph retries; graph failure reuses the validated cached extraction |
| `api/app.py` | Internal FastAPI schema/extract/read/ingest endpoints, bearer authentication, request limits, sanitized validation errors |
| `worker.py` | Daily bounded runs; signal-aware shutdown; configurable schedule |
| `cli.py` | `retrieve`, `run`, `graph-init`, `status` |

`appraisal/` and `synthesis/` remain separate future modules. No generated prose,
RoB grade, embedding-based comparability judgment, new I² computation or causal
edge is emitted in this extraction/ingestion phase.

## Install and configure

From `clarity-engine/`:

```sh
python3 -m venv .venv-pico
.venv-pico/bin/pip install -r evidence_pipeline/requirements.lock.txt
```

`requirements.txt` lists supported ranges. `requirements.lock.txt` records the
versions tested in an isolated Python 3.14 environment. The Dockerfile targets
Python 3.12; run its build and integration checks in the deployment environment.
No dependencies are added to the existing Flask requirements file.

Configure environment variables using `evidence_pipeline/.env.example` as a
reference. Local commands read process environment, or an explicitly selected
`--env-file ../.env` (which overrides stale process values). The worker accepts
`PIPELINE_ENV_FILE` for the same purpose. Compose reads the package's `.env` file. Do not commit credentials. Required for extraction:

- `EXTRACTION_PROVIDER`: `anthropic` or `openai`.
- `EXTRACTION_MODEL`: explicit model supporting the selected structured format.
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
- `PIPELINE_DAILY_CALLS`: default 20, across processes sharing the state database.
- `PIPELINE_RUN_CALLS`: default 3, conservatively counts extraction requests.

A failed/uncertain provider request consumes its reserved daily call. There are
no hidden model retries or prose fallbacks. Provider-wide configuration/auth/rate
errors stop the batch without consuming every candidate's retry allowance. Persistent extraction failures stop after three
job attempts; graph failures retain their validated extraction for replay. inspect the durable job/attempt codes before retrying. Calls and
input/output limits bound cost, not an exact currency amount.

Required for graph ingestion: `NEO4J_URI`, `NEO4J_USERNAME` (or `NEO4J_USER`), `NEO4J_PASSWORD`,
`NEO4J_DATABASE` (default `neo4j`). Use a secured Neo4j endpoint and a dedicated
account. Initial constraint creation requires schema privileges. Existing domain
nodes must have stable `id` properties; this pipeline never creates them from
unresolved model text.

## Retrieval and execution

Copy `targets.example.json` to your own configuration. The target terms are
quoted as literals, not accepted as arbitrary search syntax. The query limits
publication types to RCTs/meta-analyses and uses `FIRST_IDATE`, the first-indexed
date; it does not claim comprehensive surveillance of later corrections.
Publication-type indexing is candidate selection, not a completed design or
risk-of-bias assessment. Sources lacking an abstract or carrying a retrieved
retraction flag are retained as skipped candidates, never fabricated extracts.

```sh
python -m evidence_pipeline.cli retrieve --targets evidence_pipeline/targets.example.json --since 2026-08-01 --until 2026-09-13
python -m evidence_pipeline.cli run --targets evidence_pipeline/targets.example.json
python -m evidence_pipeline.cli graph-init
python -m evidence_pipeline.cli run --targets evidence_pipeline/targets.example.json --with-graph
python -m evidence_pipeline.cli status
# Process already retrieved papers without widening the search window:
python -m evidence_pipeline.cli run --existing-only --env-file ../.env --with-graph
```

Without explicit dates, the runner starts with a 30-day window, then uses the
last completed date with two days of overlap. A partial fixed window resumes
before a new one is opened. A page budget does not silently mark a search
complete. Retrieved records and cursor progress commit together; extraction and
graph failures do not discard those sources. `run` exits nonzero for partial
failures. Completion means the bounded run succeeded, not that every candidate
was extracted or that the literature search is exhaustive.

State defaults to `research_state/pico.sqlite3`. One local persistent disk must
be shared by API and worker. SQLite is for a single-host deployment, not multiple
replicas on network storage. Preserve this volume. A PostgreSQL state adapter is
needed before horizontally scaling this service.

## Anthropic transport and audit

The full nested approved PICO schema exceeds Anthropic's grammar compilation
limit. The adapter uses a smaller **strict field-table transport**: typed object
records, shared literal facts, and exact source passages. It expands these into
the unchanged approved Pydantic model, then runs every source/hash/reference and
statistical-bound validator. Transport compliance alone never accepts an extract.

Numeric values are parsed from literal raw tokens; no units or effects are
converted. Unicode offsets are located in the immutable document from exact
quotes and explicit occurrence indices. Missing fields are explicitly declared,
with schema-directed null/list normalization. Literal English cardinal numbers
up to 99 can be transcribed without calculating new values; their exact original
wording is retained. Explicit object references can restore omitted root indexes,
but cannot create a new scientific entity. Public-paper provider output is retained in local state for
audit, including rejected DTOs; it is never used as an accepted graph artifact.
The transport version participates in the cache key. Extraction confidence is
model-reported and uncalibrated. Abstract passage locations do not supply page or
table coordinates that the source does not contain.

Unsupported fields and invalid statistical subrecords are quarantined with an
exclusion ledger in durable state. The remaining DTO must still pass all approved
validators and minimum source-grounded PICO eligibility; an empty shell cannot
be accepted. A PICO record with source-backed sample size can be accepted without
quantitative outcomes when the source does not report them. Empty result
placeholders are removed, never counted as effect estimates. The original model
response remains immutable. Up to two schema-constrained repair calls are allowed
per failed source/model/prompt artifact, with each response, patch and error kept.
A cached response can be revalidated after a decoder fix without another API call.

## Graph design

```text
PublicationIdentifier --IDENTIFIES--> Study --HAS_EXTRACTION--> Extraction
Study --REPORTS--> StatisticalResult --MEASURES--> Outcome
StatisticalResult --IN_POPULATION--> Population
StatisticalResult --INDEX_ARM / REFERENCE_ARM--> StudyArm --USES--> Exposure
StatisticalResult --HAS_INTERVAL--> EstimateInterval
StatisticalResult --HAS_P_VALUE--> PValue
Extraction --EXTRACTED_FROM--> SourceVersion
result/component --SUPPORTED_BY--> SourceSpan --IN_SOURCE--> SourceVersion
Exposure --REFERS_TO--> existing Intervention / Biomarker
Population --HAS_CONDITION--> existing Condition
```

Local PICO nodes are scoped to an immutable extraction version. Publication
aliases deduplicate PMID/DOI/PMCID representations; conflicting existing aliases
abort the transaction. Alias locks and unique constraints support safe retries.
Ingestion can be replayed without duplicating result nodes. Graph writes commit
atomically; if the process fails after graph commit but before local job update,
the next run replays the same deterministic node IDs.

Exact values, CI levels, p-value operators and source passages remain queryable.
The complete approved payload is also retained. Re-extraction creates a new
version; downstream consumers must select a version rather than treating all
versions/follow-ups as independent studies. There is no automatic "current
clinical truth" pointer or efficacy ranking.

### Existing-node bindings

Add an explicit map to the target file after checking your domain node IDs:

```json
{
  "graph_bindings": [
    {"kind":"Intervention", "node_id":"YOUR_EXISTING_ID", "reported_name":"creatine"}
  ]
}
```

Matching is exact source wording and type. If the source says "Creatine" and the
map says "creatine", no binding is made. Unmapped source facts are still retained
as extraction-local nodes. An explicit binding to an absent or ambiguous graph
node fails the entire transaction. `Condition` bindings require a matching
reported condition on the referenced population. Names and IDs are parameters,
never Cypher fragments. No `IMPROVES`, `PREDICTS` or `CONFLICTS_WITH` relation is
inferred from an extracted ratio, p-value, matching term or vector similarity.

## Internal API

```sh
uvicorn evidence_pipeline.api.app:app --host 127.0.0.1 --port 8001
```

Set `PIPELINE_API_TOKEN` first. Every `/v1/` route requires
`Authorization: Bearer <token>`; no token configured means unavailable. Routes:

- `GET /health`: liveness/configuration flags, not a database readiness claim.
- `GET /v1/schema`: approved JSON Schema.
- `POST /v1/extractions`: `{"sources": [SourceDocument, ...]}`; returns cache key and validated envelope.
- `GET /v1/extractions/{key}`: retained extraction.
- `POST /v1/ingestions`: `{"extraction_key":"...", "bindings":[]}`; ingests only an artifact already retained by the service.

This is an authenticated **operator** API. It is not connected directly to the
public matcher and is not a patient-data ingestion endpoint. A public research
upload service still needs its existing privacy screening, tenant controls and
consent boundary before it can call this API. Arbitrary source URLs are metadata;
the API does not fetch user-supplied URLs.

## Daily deployment

`python -m evidence_pipeline.worker` runs immediately, then every 86,400 seconds.
`PIPELINE_TARGETS` selects the target file; set `PIPELINE_WITH_GRAPH=true` only
after graph initialization. `PIPELINE_INTERVAL_SECONDS` changes the cadence.
Alternatively schedule the same CLI with your hosting provider's daily cron.

The Compose file starts API and worker with one persistent state volume and
binds the API only to localhost. It connects to your configured Neo4j instance;
it does not provision a database or invent credentials.

```sh
docker compose --env-file evidence_pipeline/.env -f evidence_pipeline/compose.yaml up --build
```

The Docker-specific ignore file excludes credentials and local state from the
build context. Existing Render services are unaffected until this separate
service is explicitly configured and deployed.

## Validation and limitations

```sh
python -m unittest discover -s evidence_pipeline/tests -q
python -m evidence_pipeline.schemas.export
```

Tests cover schema bounds, exact spans, missingness, pagination/resumption,
failed checkpoints, call caching/budgets, provider strict requests and refusals,
graph projection/binding failures, replay identity, API authentication/body
limits and graph failure recovery without a second model call. Graph query tests
use a transaction double; execute the optional live graph test only against a
dedicated test database with configured credentials.

Activation check, 2026-09-14: workspace root credentials are configured and both
Anthropic and Neo4j authenticate successfully with TLS verification enabled.
All **12 retrieved publications are accepted and ingested**. Neo4j readback
verified 12 Study nodes, 59 statistical result records, 23 interval nodes and
117 source passages; all passages matched the stored immutable source text.
Outcome definitions without numeric results are not counted as estimates.

The final two publications were recovered through the token-span adapter:
`PIPELINE_EXTRACTION_MODE=spans`, Anthropic `claude-sonnet-5`. The model selects
integer token ranges; the server copies literal source bytes and validates the
approved PICO contract. Invalid observations are quarantined with an audit entry.
No source-validation rule was disabled. Earlier rejected provider outputs remain
in local audit state. Structural validation does not certify statistical interpretation.

Production loads `/etc/secrets/pico.env` and uses the existing PostgreSQL connection
for namespaced `clarity_pico_*` tables. The versioned, credential-free deployment
seed imports accepted records only when absent; existing durable records are
preserved. `/api/pico/studies` and `/api/pico/studies/<pmid>` expose source-bound
records, including a JSON download. The visual report adapter applies the stricter
plot release contract, so ingested estimates are not automatically chart points.

The data activation block can be cleared after all 12 graph writes are verified.
The daily process is separately opt-in with `CLARITY_PICO_ENABLED=1` and requires
PostgreSQL plus a host that does not sleep. A free Render web service is not a
reliable daily scheduler. Bounded calls and persisted next-run time prevent
restarts from bypassing budgets. Domain graph bindings are not configured: source
local Exposure/Population nodes are preserved without inferred causal edges.

Structural/source validation is not scientific appraisal. An exact number can
still be attached to the wrong outcome, subgroup or comparator by an extractor.
All graph artifacts remain `source_bound_extract` / `reported_extract`, not
clinically established claims. Appraisal, semantic comparability, correction
surveillance, independent-cohort resolution and deterministic synthesis need
separate acceptance contracts. Embeddings can retrieve candidates, not guarantee
comparability or agreement.

Official references: [Europe PMC API](https://europepmc.org/RestfulWebService),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Anthropic strict tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use),
[Neo4j managed transactions](https://neo4j.com/docs/python-manual/current/transactions/).

For a **disposable** Neo4j test database only, set `PICO_ALLOW_TEST_WRITES=1`
and `PICO_NEO4J_TEST_DATABASE` in addition to the Neo4j connection variables,
then run `python -m unittest evidence_pipeline.tests.test_graph_live -v`.
This test writes synthetic artifacts and leaves them in that test database for
inspection. Never point it at the production database.
