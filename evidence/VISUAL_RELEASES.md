# Automated visual evidence releases

`python3 -m evidence.visual_report ../clarity-web/public/visual-evidence.json`
rebuilds the immutable public snapshot. The catalog exporter runs the same gate.
Selected-source extraction is not a complete systematic review or a formal
risk-of-bias assessment. Public profiles do not render legacy grades or workflow
queues. Old review workflows remain internal and are not required for this path.

Contract: canonical PMID, immutable source hash, exact source and context spans,
reported finite values, supported measures, bounds, interval ordering and
contiguous point/interval tuples. No new pooled estimate, inferred interval,
clinical conclusion, NMA ranking or reconstructed curve is generated.

The research worker automatically parses eligible literal ratio findings on
publication ingestion and revisits up to 100 retained proposals per run without
LLM calls. Completed release documents are atomic records; attempts and provenance
are durable. Source fingerprint and entity-scope changes invalidate releases.
The API also suppresses bundled rows when a monitored source is observed to change.
Search coverage and source extraction dates are distinct. Retractions not retrieved
by monitored providers cannot be detected; a storage outage serves the retained
snapshot rather than claiming a new check.

Public API: `/api/visual-evidence/compound:creatine` or
`/api/visual-evidence/entity:ldl-c`. The frontend starts with its bundled snapshot
and replaces it with the current API release. Source drawers and JSON exports
retain hashes, spans, source context and extraction dates.

Launch snapshot: 30 profile records; 53 distinct eligible estimates, associated
with profiles 68 times. Eleven other findings are withheld by the gate. Cross-linked
records and follow-up publications are not independent replications.

The current automation intentionally publishes reported numerical observations
only. Formal RoB/GRADE, adjusted risk curves, pooled sensitivity analyses and NMA
require additional validated data and estimators. Chemistry uses retained
PubChem/ChEBI descriptions; paired biomarker rates use a retained source passage.

Validation: `python3 -m unittest discover -s tests -q`; `python3 test_engine.py`.
