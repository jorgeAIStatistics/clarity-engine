# Graph learning (not trained yet)

No graph neural network ships until two gates pass:

1. **Graph size.** At least ~200 non-temporary entities, with typed findings (not only PICO
   contrasts) and `RELATED_TO` edges that carry a reason. Check with
   `GET /api/evidence/graph/stats` on the live engine.
2. **Baseline first.** A logistic regression on layer counts and alias overlap is trained and
   scored on the gold set. A GNN ships only if it beats that baseline there.

At the time of writing the graph has 123 registry entities (106 biomarkers), so both tasks below
are scaffolding only. The gap ranker in `evidence/intent_graph/jobs.py` is the non-learned baseline
for "what to enrich next" that any link-prediction model must beat.

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
