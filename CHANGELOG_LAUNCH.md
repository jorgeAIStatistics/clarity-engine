# Clarity launch patch — 2026.09-launch.2

This release keeps the disclosed peptide affiliate links and focuses on scientific
integrity, reproducibility, privacy, routing, and production safety.

## Professional UI refinement

- Reworked the compound page into a publication-style reading order: understand
  the compound → evidence overview → Ask Clarity → detailed outcomes/studies →
  chemistry/pharmacokinetics → limitations/appraisal → disclosed affiliate area.
- Replaced the large circular tier ring with a restrained evidence-classification
  stamp that makes the tier basis explicit and keeps the weighted score secondary.
- Added a compact molecular identity strip near the compound title using verified
  PubChem structure/formula data when available.
- Reduced the “everything is a card” effect across the evidence legend, outcome
  reports, chemistry, pharmacokinetics, and explainer sections by using whitespace
  and separators instead of repeated boxed panels.
- Standardized evidence visuals around the same human/animal/mechanistic colors and
  tier textures, with a compact view switcher instead of a large control card.
- Made Ask Clarity a first-class evidence tool near the top of the scientific
  workflow while retaining its closed-evidence grounding, sources, timing, and
  feedback metadata.
- Upgraded study inspection into a filterable/sortable evidence matrix with
  Human/Animal/RCT/Synthesis filters, source links, and outcome-level direction
  context without pretending direction was extracted study-by-study.
- Reduced all-caps monospace typography in reader-facing headings; monospace is
  reserved mainly for provenance, identifiers, numeric metadata, and scientific
  values.
- Desktop navigation now lives in the sticky top bar; the floating bottom dock is
  retained only on mobile. EN/ES remains accessible from deep compound pages.
- Preserved the disclosed peptide affiliate purchase flow.

## Scientific/data corrections

- Compound headline study counts are deduplicated across outcomes by PMID, DOI,
  Europe PMC ID, then normalized title fallback.
- Top-level human/animal counts are unique papers rather than summed outcome
  memberships.
- Preprints can be discovered through Europe PMC but are excluded from the
  published tier calculation.
- A would-be Strong efficacy claim is capped to Moderate when effect direction
  cannot be conclusively checked; the failure state is preserved in the profile.
- Effect-extraction and direction status are explicit instead of silently lost.
- Canonical vitamin indications remain part of outcome discovery.
- The headline tier is described as the strongest/best-supported human tier,
  rather than implying every outcome has the same certainty.
- Outcome-dependent compounds are identified when human outcome tiers materially
  diverge.
- The public outcome section is phrased as outcomes ranked by evidence certainty,
  not simply “what it is good for.”
- Pharmacokinetic data now has one source of truth in backend
  `pharmacokinetics.py`; duplicate PK values were removed from JSX.
- Profiles carry engine/schema/retrieval version, generation timestamp, sources,
  and tier-basis provenance.

## Ask Clarity / privacy

- Ask Clarity V2 is retained: fast structured answers plus question-specific
  evidence retrieval for interpretive questions.
- Study citations support PMID, DOI, and Europe PMC identifiers.
- Raw Ask question/answer persistence is OFF by default.
- Quality telemetry stores a salted one-way question fingerprint, lengths,
  coverage, retrieval count, mode, and optional helpful/not-helpful feedback.
- Request history and body size are bounded.
- Stale/old-engine profiles cannot be used by Ask Clarity.

## Frontend / publication UX

- Browser routes are shareable and Back/Forward aware: `/research`,
  `/compound/:slug`, `/learn/basics`, `/learn/evidence`, `/methodology`,
  `/privacy`, `/terms`.
- Every route change jumps to the top.
- Sticky Back remains visible on compound/methodology pages.
- Privacy and Terms/medical notice pages are included.
- Compound pages show evidence source, generation date, and engine version.
- Grade labels/count wording are more precise.
- Old session grade cache is cleared before loading the current catalog.
- Key catalog cards are keyboard-operable; document language and focus styles are
  set for accessibility.
- Dynamic page title, description, and canonical metadata are updated on route
  changes.

## Production safeguards

- CORS is restricted through `CLARITY_ALLOWED_ORIGINS`.
- Security headers and Ask `no-store` response caching are set by the API.
- Public launch defaults to `CLARITY_ALLOW_LIVE_GENERATION=0`: only the audited,
  pre-generated catalog is served. This prevents a random public query from
  publishing a brand-new unaudited profile.
- Render config uses one Gunicorn worker with threads so current in-memory
  budget/rate counters remain coherent.
- Paid/non-sleeping web and persistent Postgres plan IDs are included in
  `render.yaml`; review provider cost before applying the Blueprint.

## Release tools

- `regrade_all.py` fresh-regenerates the catalog and is now actually resumable:
  profiles already on the current engine/schema are skipped on rerun.
- `launch_audit.py` blocks release on mixed engine versions, duplicate headline
  counts, graded preprints, uncited claims, Strong claims without completed
  direction verification, inconsistent per-claim counts, uncited PK, or
  placeholder generated prose.

See `PRELAUNCH.md` for the exact deployment sequence.
