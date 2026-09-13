# Health evidence expansion

The new module adds five scientific entity types without migrating or changing
existing compound profiles. `app.py` registers the evidence blueprint beside the
existing catalog, profile, and Ask endpoints.

## Entity model

`catalog.json` is the canonical versioned snapshot. Each entity has an ID, type,
evidence question, population, exposure/intervention/test, comparator, outcomes,
studies, source provenance, independent assessments, and related entities.
Precision oncology also requires cancer type, stage, molecular subtype,
biomarker, therapy, and treatment line. A biomarker and its diagnostic or screening
use are different records linked by `related` IDs.

The beta includes 10 biomarkers, 2 diagnostic/risk-stratification tests, 4 screening
programs, and 2 precision-oncology relationships. Existing intervention content
continues to use the existing `/api/profile` and efficacy grader.

## Appraisal policy

`appraisal.grade_entity` dispatches by entity type. Intervention outcomes use
`grade.grade_outcome`. All other entities use independent review dimensions:

- Biomarkers: analytical validity, biological variability, association strength,
  incremental predictive value, causal evidence, and clinical utility.
- Diagnostics: reference standard, sensitivity, specificity, applicability, bias.
- Screening: mortality, stage, overdiagnosis, false positives, procedures,
  psychological harms, and number needed to screen.
- Oncology: assay validity, prognosis, treatment interaction, benefit, applicability.

There is no aggregate biomarker/test grade. A non-empty grade requires a named
reviewer, review date, rationale, linked sources already in the entity, population,
outcome, and limitations. Study counts do not automatically confer a strong grade.
Reference summaries are educational source summaries, **not systematic reviews**.
Most beta dimensions intentionally remain `Not yet assessed`. This describes the
catalog's appraisal coverage rather than the underlying state of medicine.

To apply a completed review, supply JSON with `entity_id`, `catalog_version`, and
`reviews` keyed by the exact dimension names. Each completed dimension has `rating`
(Strong, Moderate, Limited, or Insufficient), `reviewer`, `reviewed_at`, `rationale`,
`source_ids` (study IDs or source URLs already present), `population`, `outcome`,
and `limitations`. Run `python3 -m evidence.review review.json --output reviewed.json`,
inspect it, then replace the canonical catalog and export it. Do not put patient
identifiers in catalog records.

## API

- `GET /api/entities?entity_type=biomarker&q=apob&condition=Cardiovascular`
- `GET /api/entities/apob`
- `GET /api/entities/apob/assessment`
- `GET /api/evidence/frameworks`
- `POST /api/statistics/diagnostic`: sensitivity, specificity, prevalence (0–1),
  optional population (integer 1–1,000,000).
- `POST /api/statistics/screening`: baseline_risk, screened_risk (0–1), optional
  false_positive_risk and procedure_risk (0–1).

Invalid types, booleans, nonfinite/out-of-range probabilities, and unknown input
fields are rejected. Ratios with a zero denominator return JSON null. Null never
means zero. Expected cohort counts may be fractional. NNS uses the reciprocal of
absolute risk reduction rounded up; an increase in risk is represented as NNH.
These are deterministic calculations, not individual medical predictions.

## Export and deployment

The frontend and engine are separate Git repositories. The frontend bundles a
validated snapshot so it works before the new API is deployed and while offline.
After catalog edits, run from clarity-engine:

```sh
python3 -m evidence.export_catalog ../clarity-web/src/evidence/catalog.json
python3 -m unittest discover -s tests
python3 test_engine.py
```

Deploy the engine using its existing process, and build/deploy clarity-web using
its existing static-site process. The engine does not need database changes or new
credentials. No production deployment was performed as part of this implementation.

## Scientific graphics

The frontend has provenance-checked renderers for risk curves, distributions,
longitudinal series, correlation matrices, ROC/AUC, calibration, Kaplan–Meier
curves, forest plots, and treatment-response matrices. An entity's optional
`figures` list accepts the model documented by `src/evidence/figures.js` in the web
repository. Real figures require a source URL; teaching examples require the
explicit `illustrative` flag. Real survival curves must come from published
coordinates or observed event/censoring data, never reconstructed from medians.

FLAURA has a sourced overall-survival interval plot. Its 2019 trial comparison is
not a current treatment recommendation and does not establish an interaction
between biomarker status and treatment. The HERA reference explicitly separates
the four-year recurrence and overall-survival findings.

Future editorial work: systematic searches, study extraction, independent expert
appraisal, and population-specific accuracy/benefit-harm estimates for the seed
profiles. Those values must not be generated from the illustrative calculators.
