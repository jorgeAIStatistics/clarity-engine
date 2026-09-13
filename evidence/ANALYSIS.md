# Study-level analytical profiles

`analysis.py` interprets retained outcome-level effect extractions without making
new paid calls, collecting new studies, or inventing a pooled estimate. The
original cached profile remains intact; `/api/profile` includes an additive
`analysis` object.

An estimate is included only when it is marked verified, is not converted or
based on an estimated interval, has a source record within that outcome, has
finite ordered bounds, and its numerical values occur in its retained passage.
Protocols and preprints are excluded. Unsupported measures and missing intervals
are withheld with explicit reasons. Source identity must match the outcome.

The source passage can come from an existing extraction rather than the bounded
abstract stored in the profile. `quote_in_retained_abstract` exposes this
provenance distinction. Numerical consistency is not proof of semantic validity;
original source review remains necessary. Confidence versus credible intervals
and reported confidence levels are preserved. Unreported levels stay null.

Absolute units are recovered only when attached to the reported estimate.
Otherwise the estimate can be inspected but is not placed on a common axis.
Ratios require positive values and have a no-difference value of one; absolute
and standardized differences have a no-difference value of zero. Crossing that
value is not interpreted as equivalence. Above/below-null intervals are not
automatically described as clinical benefit.

Context mentions are exact spans from the stored title/abstract. They are labeled
as mentions, not complete eligibility criteria, dosing instructions, or follow-up
estimates. No participant totals are added across trials/reviews, no formal bias
judgments are generated, and no pooled estimate is created. Reviews can overlap.

The unified inventory (`library.py`) enumerates cached compounds plus the entity
catalog, deduplicating repeated cached names. `available` reflects engine/schema
availability; `review_status` separately flags protocols and incomplete appraisal.
The API snapshot is cached for five minutes. The CLI creates a dated static
fallback for the frontend.

Local audit: 161 profiles, all 161 API links returned 200. Sixty-six intervention
profiles contained eligible numerical estimates. Across the retained cache, 222
estimates passed and 637 were withheld. These are extraction counts, not unique
studies or evidence of effect. Twenty profiles require protocol-related appraisal
refresh. No cached grade was silently recomputed.

Run `python3 -m unittest discover -s tests` and `python3 test_engine.py` before
changing the analysis policy. Frontend tests cover ratio axes, no-difference
values, layer separation, deduplication, and endpoint-specific attribution.
