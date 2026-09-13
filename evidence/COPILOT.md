# Question-aware research navigation

`matcher.py` ranks the retained entity/study index; `copilot.py` organizes the
selected records around explicit question fields and six research angles.
No model API, embeddings, saved queries or new service is required. CSV/TSV
mapping submits the same bounded text request. The browser keeps raw files local.

The question reading is deterministic and provisional: phrase rules do not fully
understand negation, arbitrary study designs or every endpoint. Users can correct
the text. Groups are candidate reading sets, not systematic reviews or automated
agreement judgments. Numerical findings remain literal, source-specific extracts;
shared publications preserve marker-specific populations, exposures and estimates.
Coverage counts are not confidence scores. Missing records mean a retrieval gap,
not absence in the full literature. Graph edges are catalog connections, not clinical
interactions. Clinical utility requires a management-strategy comparison and is not
inferred from a drug trial alone.

## Optional feedback and enrichment priority

`POST /api/evidence/match/feedback` accepts a signed, one-hour result token plus
one fixed code (helpful, not_relevant, missing_angle) and, for missing_angle, one
fixed research-angle ID. Tokens bind server-selected catalog IDs; replay is idempotent.
The existing research store retains only an event ID, code, angle, named catalog IDs,
version and timestamp. It never stores question text, tables or source passages.

`CLARITY_FEEDBACK_SECRET` can supply a stable random server secret. Without it,
a process-local random key is used; restarting the process invalidates outstanding
tokens and users must rerun matching. Set the same secret across processes before
scaling to multiple web workers. Never commit this secret.

The scheduler considers at most 2,000 recent feedback records and 1,000 reviewed
rejected proposals over 30 days. Missing-angle signals add at most eight priority
points; recent review rejections add at most twelve. Only already-due catalog targets
are reordered. Existing budgets, checkpoints, leases, impact gates and review rules
remain authoritative. Helpful/not-relevant counts are available for operator review;
they do not train a model or rewrite evidence grades. Run `python3 -m evidence.feedback`
for a compact count/priority report. Events older than 30 days remain audit records
but do not affect priority.

## Validation

`python3 -m unittest discover -s tests -q` covers the ApoB/LDL-C/HbA1c success
question, angle classification, marker-specific provenance, broad-token suppression,
mapped input, absence of agreement verdicts, feedback tampering/expiry/replay, and
bounded scheduling signals. Browser verification covers angle filters, source jumps,
390px layout, mapped CSV results and optional feedback.
