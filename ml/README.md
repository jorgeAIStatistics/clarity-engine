# Graph learning (not trained yet)

No graph neural network ships until two gates pass:

1. **Graph size.** At least ~200 non-temporary entities, with typed findings (not only PICO
   contrasts) and `RELATED_TO` edges that carry a reason. Check with
   `GET /api/evidence/graph/stats` on the live engine.
2. **Baseline first.** A logistic regression on layer counts and alias overlap is trained and
   scored on the gold set. A GNN ships only if it beats that baseline there.

## Graph size on 2026-09-19 — the gate does not pass

| | count | required |
|---|---|---|
| Entities (non-temporary) | 174 | 200 |
| **Linked** findings | **114** | 200 |
| Findings stored in total | 176 | — |
| Baseline exists | yes | yes |

The gate counts LINKED findings, not stored ones. 176 is every row the decoder kept; 114 of those
carry an ABOUT edge to an entity. The difference is findings whose marker span named nothing in the
registry, plus three that a paper quoted from other papers and which are deliberately linked to
nothing. Counting the larger number would let the gate pass on evidence the graph does not hold.

Findings by kind: association 24, classification 49, discrimination 49, effect 19, guideline 3,
prognosis 32. By provenance: primary 5, cited 3, unclear 168.
Aliases 390, typed relations 47, dead-letters 36, questions 13.

**No GNN is trained**, and `ml/gnn` is a stub that raises if called. When the gate passes, the
comparison is fixed in advance: a held-out RELATED_TO edge or "utility-evidence likely vs
association-only", split by paper AND by entity so a model cannot be scored on findings from a
study it trained on, against `ml/gap_ranker.py` on the same split. It ships only if it beats that
baseline. `python -m ml.export` rewrites these numbers and the gate into the dated manifest.

## Entity linker (shipped as offline tooling, `ml/linker.py`)

Character n-gram TF-IDF over alias strings with cosine retrieval, then a hard filter. It is a
lexical vector space — nothing is trained, no API is called — and it is described that way on
purpose.

Run on 2026-09-18, 26 gold cases:

| | gold precision | gold recall | hijacks | spelling/spacing cases |
|---|---|---|---|---|
| Exact alias matching (live path) | 1.0 | 1.0 | 0 | 8/10 |
| This linker | 1.000 | 1.000 | 0 | 10/10 |

The deterministic MENTIONS path scores the same 26 cases at precision 1.0 / recall 1.0 with no
forbidden attachment, and that one runs in CI with no third-party package installed.

Gold set: 26 questions. The linker earns its place on variation exact matching misses
("Interleukin 18 levels", "CA 125", "NT pro BNP", "p-tau 181"), not on the gold set, where the
live path is already perfect.

Three gold cases were added to keep one acronym's three objects apart — the EGFR protein, the EGFR
gene and an EGFR activating variant — and a fourth for the IL18 gene against the IL-18 protein. That
last case failed the moment it was written: the linker attached the protein to a question about the
gene. It kept the *last* window that matched an entity rather than the strongest, so a weak prefix
match on "IL18 gene polymorphism and" overwrote the literal "IL18 gene" and disarmed the suppression
rule below. It now keeps the best evidence per entity, and containment is compared per word with
punctuation squeezed, so "IL-18" is one word inside "IL18 gene" while "ER" is still not a word
inside "breast cancer".

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

## Gap ranker — a baseline that is allowed to break ties, and nothing more (`ml/gap_ranker.py`)

Label: the outcome of an enrichment attempt already made — a typed finding (1) or a dead-letter (0).
Features are restricted to what was knowable before that attempt (publications, aliases, demand,
kind, curated identity). Finding counts are excluded on purpose: they are the label in disguise,
and `tests/test_gap_ranker.py` asserts they cannot reach the model.

| | 22 attempts (2026-09-16) | 32 attempts (2026-09-17) |
|---|---|---|
| Labelled attempts | 22 (17 found, 5 dead-lettered) | 32 (21 found, 11 dead-lettered) |
| Leave-one-out accuracy | 0.727 | 0.750 |
| Majority class | 0.773 | 0.656 |
| Leave-one-out AUC | 0.624 | 0.706 |
| Sets the ranking | **no** | **no** |
| Breaks ties within a need score | no | **yes** |

On 32 attempts the baseline beats the majority class for the first time. It still does not become
the ranking, and that is a design choice rather than a threshold: this model predicts which attempt
will *succeed*, so ranking by it would put the easy targets first and starve the gaps the library
actually has. Need stays the ranking, and the model is allowed to order entities the need rule
scores equally — which is exactly where "which of these is likeliest to return a finding" is the
open question. `tests/test_gap_ranker.py` asserts it can do that and no more.

An accuracy from 32 leave-one-out folds has a wide interval. Treat the comparison as a sanity check
that the features carry signal, not as a measurement of how well the model works.

The rule is deliberately *not* scored against this label: it ranks need — an empty page scores
high — while the model predicts whether an attempt would succeed. An AUC between them would be
inverted by construction, so no head-to-head number is published.

Predictions are written as `(:Prediction {task:'gap', score, model, version, review_state})-[:ABOUT]->(:Entity)`.
The current queue is in `docs/gap-queue.md` and `ml/exports/<date>/gap_queue.json`.
