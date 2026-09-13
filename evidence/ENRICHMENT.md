# Selected-source enrichment

The September 13, 2026 pass adds 15 selected publications across 17 domain profiles. It is targeted enrichment, not an exhaustive literature review or a completed search window. It adds non-HDL cholesterol, cystatin C, and MSI-H/dMMR colorectal cancer × pembrolizumab with populated records.

`source_snapshot.json` retains normalized MEDLINE abstracts retrieved from Europe PMC, stable identifiers, retrieval dates, exact identifier queries, and SHA-256 hashes. Text normalization removes known presentation tags, decodes HTML entities, and collapses whitespace; it preserves comparison operators such as `P<0.001`. Source spans use offsets in that normalized text.

A study is a publication with a PMID and optional shared `cohort_id`. Its `findings` array holds separate outcome estimates and quote spans. Publications from the same trial (FLAURA) remain linked, not summed as independent populations. Quantified-outcome counts deduplicate endpoint names; study counts deduplicate publication identities.

All new records are `automated_appraisal`, with `human_verified: false`. No existing clinical evidence grade was changed. Estimates reproduce reported values; no missing confidence intervals, participant counts, or personal-health interpretations are inferred. Cohort and diagnostic results are not presented as intervention effects. Selected-source extraction dates never substitute for a completed monitoring date.

Run `python3 -m unittest discover -s tests -q` and `python3 -m evidence.export_catalog ../clarity-web/src/evidence/catalog.json` before publishing. Export fails if source spans or numeric provenance fail validation. Regenerate the bundled inventory with `python3 -m evidence.library --output ../clarity-web/public/library.json`.

Incremental monitoring still uses the existing persistent cursors, deduplication, bounded extraction budget, split date windows, and review queue. High-value enriched profiles receive explicit scheduling priority in `living_research/config.example.json`; daily model budgets are unchanged. Grade changes and scientific support/contradiction judgments must enter the human review workflow. The matcher remains lexical/entity retrieval and never performs those judgments.
