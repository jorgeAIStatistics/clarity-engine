# Question-first Neo4j matcher

The map endpoint (`POST /api/evidence/match`, `workspace: true`) parses the submitted
question with Claude before resolving anything. No catalog is in the parser prompt.
Pydantic requires entities with exact input spans, outcomes, population, exposure,
question intents and exclusion guards. Population/settings/endpoints absent from the
literal input cannot become retrieval constraints. Exact written aliases recover
missed concepts and override ambiguous model types. Unresolved spans become temporary
entities; catalog siblings never replace them.

Neo4j `Entity` / `Biomarker` nodes own aliases and five `LayerAssessment` nodes.
`MENTIONS_ENTITY` records an exact alias in retained source text, not causality.
Only those entities' Study/MatcherRecord records are retrieved. Disease, setting and
outcome constraints apply before ranking and coverage counts. GAP is indexed coverage,
not an absence-of-literature claim. Metadata-only records have no eligible plot numbers.

Temporary nodes contain entity names only and expire after seven days; expired nodes
and their layers are deleted on the next resolution. Full submitted questions and
uploaded tables are not stored in Neo4j. The frontend discloses that Claude parses the
question. The existing personal-health/identifier rejection runs before model calls.

## When Claude or Neo4j is unavailable

`service.run` never falls back to the old lexical catalog matcher. If the Claude key is
missing, the daily cap is spent, the parse is rejected, or Neo4j cannot be reached, the
map is built by `run_local`: rule-based fields taken only from literal spans of the
question (outcome phrases, population, treatment setting, question types), exact alias
resolution against `registry.json`, temporary in-memory rows for unrecognized marker
names, and retained library records constrained to those entities, outcome and setting.
The response carries `parse: {mode: "rules", reason}` and Panel A says the automatic
parser was unavailable. On the 20-question gold set this path scores 46 true positives,
0 false positives and 0 false negatives, with no forbidden entity.

## Configuration

- `ANTHROPIC_API_KEY`: environment only.
- `CLARITY_INTENT_MODEL`: default `claude-sonnet-4-6`.
- `CLARITY_INTENT_DAILY_CALLS`: persistent separate daily cap, default 100.
- `NEO4J_URI`, `NEO4J_USER`/`NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`.
- `PIPELINE_DATABASE_URL`: PostgreSQL state in production; SQLite for local audits.

`python -m evidence.intent_graph.seed` idempotently seeds 108 biomarker alias entries
and migrates source-checked records. It does not invent effect sizes or certify the
registry as clinically validated. `python -m evidence.intent_graph.enrich` performs a
checkpointed extraction pass for 30 named cancer markers plus IL-18 and NfL, capped at
one source per marker per pass and three concurrent requests. Failed validation stays
in the audit store. `CLARITY_RETRY_ENRICHMENT=1` selects another source for failed entries.

## Evaluation / PR evidence

`gold.json` contains 20 questions, including the exact IL-18 title, NfL/ALS, ApoB/LDL-C,
ambiguous EGFR/eGFR, and cancer markers. `eval-results.json` is a live Claude evaluation:
**46 true positives, 0 false positives, 0 false negatives; precision 1.000, recall 1.000**.
This is a small regression set, not an estimate of general biomedical linking accuracy.
The initial run had recall 0.913 with no false positives; explicit-span recovery fixed
its four misses. No embedding infrastructure or patient-level training was added.

## Figures

Published plotted numbers must come from source-validated Neo4j findings explicitly
marked `plot_eligible`; the legacy frontend snapshot is not mixed into a graph result.
CSV overlays remain browser-local aggregate rows. Forest strips show source-specific
intervals on ratio/log or difference/linear axes, without pooling. Box/IQR summaries
require at least five unique-source records with the same recorded outcome, measure,
unit, population, exposure, comparator and timepoint. Missing/incompatible context
suppresses the distribution, not the source records. Quartiles are descriptive; they
are not a new meta-analysis. Every figure includes a caption, limits, and interpretation.

Histograms/violins of patient values and biomarker-outcome scatterplots are not drawn
from effect-size tables. Those require genuinely observed distribution bins or paired
aggregate measures with definitions, units and sample counts. No fabricated raw points,
clinical decisions, support/contradiction verdicts or synthesized efficacy edges are used.
