# Researcher retrieval contract

POST /api/evidence/match accepts one JSON string field `text` (20–12,000 chars).
It returns ranked entities and unique study records, relevance explanations,
verbatim source passages with character spans, missing appraisal fields, and
related questions. Query text is processed in memory, never persisted, embedded
in a URL, sent to a model provider, or included in application log messages.
Responses are `Cache-Control: no-store`.

The first implementation uses alias matching, a small explicit biomedical concept
vocabulary and inverse-frequency lexical ranking. It is not embedding retrieval
or a scientific entailment classifier. Supporting/contradicting result slots are
explicitly `requires_review`; text similarity cannot establish agreement.

## Extension contracts

- Retrieval providers: replace the ranking strategy while preserving source IDs,
  matched entity IDs, passage offsets, corpus coverage, and method/version fields.
- Entity nodes: stable `id`, `entity_type`, `name`, `aliases`, canonical `path`,
  `outcomes`, and source references. Current concrete types are intervention,
  biomarker, diagnostic, screening, and precision_oncology. Conditions are
  navigation contexts; pathway nodes require curated source-backed edges before
  receiving clinical profiles. No generated condition/pathway grades.
- Relation edges: source entity, target entity, relation type, study ID, quote,
  population/outcome context, and review state. Navigation links must never be
  interpreted as causal or treatment edges.
- CSV/JSON uploads: future schema-validation adapter, explicit units, no inference
  from unlabelled values. No personal-health assessment endpoint.
- Private workspaces: require authentication, tenant isolation, deletion/export
  controls and explicit storage consent before persisting research inputs.
- Study-design and agreement models: separate reviewed layers; preserve uncertainty
  and leave unsupported classifications unknown.

The corpus index is cached for one hour. Result count and query size are bounded;
no paid model calls occur. Monitoring prioritization accepts aggregate monthly
views in operator config, observed recent publication volume, and overdue age.
Missing traffic is zero, not an invented popularity estimate.
