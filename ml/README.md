# Graph learning (not trained yet)

No graph neural network ships until two gates pass:

1. **Graph size.** At least ~200 non-temporary entities, with typed findings (not only PICO
   contrasts) and `RELATED_TO` edges that carry a reason. Check with
   `GET /api/evidence/graph/stats` on the live engine.
2. **Baseline first.** A logistic regression on layer counts and alias overlap is trained and
   scored on the gold set. A GNN ships only if it beats that baseline there.

## Graph size on 2026-09-16 — the gate does not pass

| | count | required |
|---|---|---|
| Entities (non-temporary) | 174 | 200 |
| Typed findings | 78 | 200 |

Findings by kind: association 16, classification 24, discrimination 25, effect 1, guideline 1, prognosis 11.
Aliases 390, MENTIONS 258, typed relations 47.

**No GNN is trained.** Both gates fail, and a heterogeneous link-prediction model fitted on 78
findings would be a demonstration, not a result. `python -m ml.export` refreshes the numbers.

## Entity linker (shipped as offline tooling, `ml/linker.py`)

Character n-gram TF-IDF over alias strings with cosine retrieval, then a hard filter. It is a
lexical vector space — nothing is trained, no API is called — and it is described that way on
purpose.

| | gold precision | gold recall | hijacks | spelling/spacing cases |
|---|---|---|---|---|
| Exact alias matching (live path) | 1.0 | 1.0 | 0 | 8/10 |
| This linker | 1.000 | 1.000 | 0 | 10/10 |

Gold set: 23 questions. The linker earns its place on variation exact matching misses
("Interleukin 18 levels", "CA 125", "NT pro BNP", "p-tau 181"), not on the gold set, where the
live path is already perfect.

Three rules keep retrieval from becoming injection, and each one was added because the evaluation
caught the failure:

1. **Case is identity for an acronym.** The first version attached the EGFR receptor to a question
   about eGFR (kidney function), because normalising lowercased both.
2. **A shared word must be distinctive.** Sharing "mutation", "cancer" or "screening" attached
   unrelated entities; which words are distinctive is read off the registry, not hand-listed.
3. **Similarity alone attaches nothing.** One name must be the start of the other, and only a name
   actually written in the question may suppress another entity — as whole words, so "ER" is not
   swallowed by "breast canc-er".

Tests: `tests/test_linker.py` (skipped where scikit-learn is absent).

## Tasks

- **Link prediction (primary).** Rank missing `RELATED_TO` edges, or "this marker likely has
  utility evidence rather than only association". The output is a ranked enrichment list or a
  Panel E suggestion, never a clinical score.
- **Node classification.** Predict the dominant finding kind or layer completeness, to route an
  abstract to the diagnostic or interventional extractor.

Predictions are stored as
`(:Prediction {task, score, model, version, review_state:'automated'})-[:ABOUT]->(e:Entity)`.
The website may say "model suggests enriching the utility layer"; it must never say "treat with X".

## Export (Cypher)

```cypher
// Nodes: one row per entity with layer statistics
MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false
OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)
WITH e, collect({layer:l.layer, n:coalesce(l.n_findings,0), status:l.status}) AS layers
OPTIONAL MATCH (e)<-[:ABOUT]-(f:Finding)
RETURN e.id AS id, e.kind AS kind, size(e.aliases) AS aliases, layers,
       [k IN collect(f.kind) WHERE k IS NOT NULL] AS finding_kinds;

// Typed edges (heterogeneous; never flatten entities that only share a disease)
MATCH (a:Entity)-[r:ENCODED_BY|VARIANT_OF|IN_PATHWAY|MEASURED_BY|RELATED_TO]->(b:Entity)
RETURN a.id AS source, type(r) AS edge, r.reason AS reason, b.id AS target;

// Entity–finding–study incidence for bipartite features
MATCH (s:Study)-[:REPORTS]->(f:Finding)-[:ABOUT]->(e:Entity)
RETURN s.id AS study, f.id AS finding, f.kind AS kind, e.id AS entity;
```

## Splits

Split by entity or by paper, never by random edges alone: a random edge split leaks the same
paper's findings into train and test.

## Baseline interface

```python
def baseline_features(node_row) -> list[float]:
    """Layer n_findings for the five layers, counts per finding kind, alias count."""

def fit_baseline(rows, labels) -> "sklearn.linear_model.LogisticRegression": ...

def score(model, rows) -> list[float]: ...
```

Candidate GNN stacks, used only after the baseline: Neo4j GDS (GraphSAGE / HinSAGE) if GDS is
available on the database, otherwise PyTorch Geometric heterogeneous GraphSAGE in this package.

## Gap ranker — baseline fitted, and not adopted (`ml/gap_ranker.py`)

Label: the outcome of an enrichment attempt already made — a typed finding (1) or a dead-letter (0).
Features are restricted to what was knowable before that attempt (publications, aliases, demand,
kind, curated identity). Finding counts are excluded on purpose: they are the label in disguise,
and `tests/test_gap_ranker.py` asserts they cannot reach the model.

| | value |
|---|---|
| Labelled attempts | 22 (17 produced a finding, 5 dead-lettered) |
| Leave-one-out accuracy | 0.727 |
| Majority class | 0.773 |
| Leave-one-out AUC | 0.624 |
| Adopted as the ranking | **no** |

The model does not beat the majority class on 22 attempts, so the shipped queue is
ranked by the need rule in `evidence/intent_graph/jobs.py` and the model's probability is shown
beside it for comparison only.

The rule is deliberately *not* scored against this label: it ranks need — an empty page scores
high — while the model predicts whether an attempt would succeed. An AUC between them would be
inverted by construction, so no head-to-head number is published.

Predictions are written as `(:Prediction {task:'gap', score, model, version, review_state})-[:ABOUT]->(:Entity)`.
The current queue is in `docs/enrich-queue.md` and `ml/exports/<date>/gap_queue.json`.
