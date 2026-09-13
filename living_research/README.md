# Clarity living research agent

One pipeline covers interventions, biomarkers, diagnostics, screening, and
precision oncology. It discovers all entity catalog records and cached compound
profiles at the start of every run. On this workspace that is **161 subjects**:
143 compounds and 18 new-domain profiles. New catalog records join automatically.

The agent performs bounded retrieval → identity deduplication → source-grounded
LLM extraction → structured proposal → explicit review → publication. Its public
output is a reviewed research update with source passages, population/context,
evidence type, and timestamps. It never silently recomputes clinical grades or
uses an intervention grade for a biomarker, test, or screening program.

## What is automated

- Free metadata triage classifies candidate study designs and prioritizes possible
  corrections, safety content, and informative studies. Scores order work; they
  do not establish clinical impact. Queue aging prevents indefinite starvation.
- Standard extraction uses `CLARITY_RESEARCH_MODEL`; high-priority work can use
  `CLARITY_RESEARCH_STRONG_MODEL`. If omitted, both use the standard model. Both
  tiers share the same daily and per-run request limits.
- Grounded extraction is cached by entity context, exact source text, source URL,
  schema version, and model. Bibliographic-only changes reuse extraction; new
  text or a changed population/question requires extraction again. Separate
  entities do not share context-specific clinical extraction.

- PubMed modification-date queries (E-utilities), Europe PMC update-date queries,
  and ClinicalTrials.gov last-update queries, with aliases and oncology context.
- API throttling/retries, paginated retrieval, recursive splitting of oversized
  date windows, and a seven-day overlap for indexing delays.
- Per-source/entity checkpoints. A failed/incomplete source does not advance its
  checkpoint or replace previously published evidence. Same-day overflow is an
  explicit failure requiring a larger record cap, never a silently truncated run.
- PMID/PMCID/DOI identity unions; registries retain NCT identities and are not
  counted as publications. Raw provider versions and exact queries are preserved.
- Change fingerprints: an unchanged record does not generate another proposal.
  Changed records supersede unpublished proposals. Entity-context changes reset
  the monitoring window and invalidate old-context publication approvals.
- Optional Anthropic extraction using the existing project model configuration,
  bounded to 20 calls per run and 100 calls per UTC day by default. Call slots are
  reserved persistently before requests, including failed calls. No paid extraction
  occurs unless `--llm` is supplied and a key is configured.
- Extracted facts require exact source quotes, and numbers in claims must occur
  in those quotes. Full-text availability is not assumed: the model sees the
  retrieved abstract/registry record, capped at 24,000 characters and labeled if
  truncated. This is targeted retrieval grounding, not an embedding/vector system.
- Separate population layers, test thresholds/reference standards, screening
  follow-up/harms, and cancer stage/subtype/treatment interaction fields.
- Candidate safety, mortality, retraction/correction, preprint, and trial-registry
  flags for the reviewer. These are triage flags, not established clinical signals.
- A persistent retry queue for LLM failures; after three failed attempts an item
  is labeled `extraction_failed` for operator attention.

## Run locally

From clarity-engine:

```sh
python3 -m living_research targets
python3 -m living_research --config living_research/config.example.json run --only entity:apob
python3 -m living_research --config living_research/config.example.json run --only entity:apob --llm
python3 -m living_research status
python3 -m living_research proposals --status review_ready
```

No-LLM mode collects metadata and creates `awaiting_extraction` proposals. The
source integration smoke test used a separate `research_state/smoke.sqlite3`,
queried one day's ApoB updates, and made **zero paid AI calls**. That smoke database
is not the public site's research state and is excluded from Git.

Configure `ANTHROPIC_API_KEY` and, optionally, `CLARITY_RESEARCH_MODEL`. The model
falls back to the project's existing `CLARITY_LLM_MODEL` setting. A different model
can be configured without code changes. NCBI requests can use `NCBI_API_KEY` and
`CLARITY_CONTACT_EMAIL`. Keys are read only from environment variables and never
stored in search logs. Configure the model and budget deliberately before starting
continuous extraction. The daily limit bounds requests, not an exact dollar cost.

## Continuous operation

```sh
python3 -m living_research --config living_research/config.example.json watch --llm
```

The worker checks for due work hourly. Most subjects become due every seven days;
priority subjects in the example config are checked daily or every three days.
Up to 25 due subjects are processed per run, oldest-due first. The two budgets are
independent: monitoring can continue while the AI extraction queue waits for the
next budget window. Increase target throughput as the catalog grows.

Use a supervised background worker in production, rather than a browser tab or
web request. `render-worker.yaml` is an optional worker blueprint; it has **not**
been deployed or activated. Give the API and worker the same PostgreSQL
`DATABASE_URL` so published updates are immediately available to the site. There
is no need to rebuild the frontend when an approved research note is published.
The worker itself must be deployed to enable continual operation. A local process
stops monitoring when the computer sleeps or the process exits.

Storage preference: `CLARITY_RESEARCH_DATABASE_URL`, then `DATABASE_URL`, then
local `research_state/living.sqlite3`. SQLite is useful locally; use PostgreSQL for
separate deployed API and worker processes. Tables and lookup indexes are created
idempotently. A renewable lease prevents concurrent monitors and protects review
and publication from racing with ingestion. Publication is transactional.

## Review and publication

```sh
python3 -m living_research approve PROPOSAL_ID --reviewer 'Reviewer name' --note 'Source checked; describe the relevant change and limitations.'
python3 -m living_research publish PROPOSAL_ID
python3 -m living_research reject PROPOSAL_ID --reviewer 'Reviewer name' --note 'Explain exclusion.'
```

Approval attests that the reviewer checked the extracted claims and passages.
Metadata-only items cannot be approved before grounded extraction. Source quote
matching is not a substitute for checking meaning, relevance, population,
confounding, publication status, or applicability. Review the proposed note and
all extracted facts before approval. No public write/review endpoint is exposed.

Each proposal stores the publication before/after diff, source fingerprints,
applicable dimensions, extraction provenance, triage flags, and baseline version.
If another proposal is published first, publication fails closed. Run
`python3 -m living_research rebase PROPOSAL_ID`, inspect the changed baseline, then
review it again. Rebase clears the previous approval. Changes to clinical ratings
remain in the independent domain appraisal workflow (`evidence/review.py`). For
compound grades, reassess the complete evidence with the existing engine and its
regression checks; a delta-only publication should not regrade the entire field.

Rejected and superseded items remain in the audit trail. Failed extractions can
be inspected with `proposals --status extraction_failed`; fix the cause before
requeueing them through the state-management API or a new extraction version.

## Public integration

`GET /api/living-research/entity:apob` or
`GET /api/living-research/compound:creatine-monohydrate` returns completed-check
freshness, pending-review count, and published notes. Unreviewed findings never
appear as clinical conclusions. The “Living research” component is present on
compound pages and every new entity type. An undeployed/unavailable API displays
an honest disconnected state; it never pretends the literature is current.

## Verification and scope

```sh
python3 -m unittest discover -s tests
python3 test_engine.py
```

Tests cover all domains, quote/numeric validation, record identity bridges,
idempotent runs, failed-source checkpoints, leases, review/publication gates,
stale baselines, changed-record supersession, rich PubMed XML, and date splitting.
Live smoke retrieval succeeded against all three services. PostgreSQL deployment
and paid model calls require the configured production environment and were not
exercised by the no-cost smoke run.

Semantic Scholar, Crossref, publisher full text, citation-graph expansion, vector
search, and guideline-specific connectors can be added as further adapters. The
current implementation uses the three biomedical sources above; it does not
scrape Google Scholar or claim exhaustive systematic-review coverage.

The common `evidence/profile.py` contract is included in compound and entity API
responses. It separates primary evidence layers, overlapping syntheses, and
unclassified records without changing existing grades. Source coverage dates
remain null unless supplied by the completed monitoring workflow. Guidelines are
recognized in indexed metadata; comprehensive society/USPSTF surveillance,
embeddings, traffic telemetry, and autonomous narrative synthesis are not enabled.
Cadence is configured per target; use a 30-day interval for stable subjects and
shorter intervals for operator-prioritized topics. No usage metrics are invented.

Official source references:
- NCBI E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25499/
- Europe PMC: https://europepmc.org/RestfulWebService
- ClinicalTrials.gov: https://clinicaltrials.gov/data-about-studies/learn-about-api

### Existing Render service deployment

The root Blueprint and Procfile now start `python production.py`. This supervises
one threaded Gunicorn process and one scheduler process on the existing service.
The scheduler starts only with a PostgreSQL DSN; it enables quote extraction only
when ANTHROPIC_API_KEY is present. Set CLARITY_RESEARCH_ENABLED=0 to disable the
scheduler independently. No new Render service or subscription is created.

The default policy allows 20 AI calls per run, 100 per UTC day, and 25 due targets
per hourly pass. All stored intervention and catalog profiles are discovered.
Conditions remain cross-domain navigation contexts, not independent graded
profiles. Newly discovered source records do not become published claims until
an operator approves and publishes the proposal through the CLI.

`GET /api/living-research/status` reports a persisted scheduler heartbeat and the
last completed run status. A deploy alone is not proof that monitoring is active.

Synthesis module `synthesis.py` assembles threshold-qualified proposals from the
reviewed baseline plus a direct-relevance candidate. Population layers, per-study
outcomes and source quotations remain separate. It does not invent pooled
estimates, change grades or reconstruct unavailable clinical curves. The full
proposal returned by `proposals` includes this review artifact and audit ID links.
Source spans use Python string offsets into `source_text(paper)`.
