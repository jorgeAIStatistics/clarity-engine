# Suggested extraction queue

Generated 2026-09-19T20:06:09Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.814 against a majority class of 0.610 on 59 attempts (AUC 0.807). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 59 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

n_findings and n_utility are the counts the ranker read, so a row can be checked against the graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: a trial of a drug is not evidence that measuring the marker helps.

| # | id | name | n_linked | n_primary | n_cited | n_unclear | n_utility | n_pubs | demand | need | baseline p | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `biomarker:ca-15-3` | CA 15-3 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.5469 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 2 | `biomarker:ca-27-29` | CA 27.29 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.5469 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 3 | `biomarker:non-hdl-c` | non-HDL-C | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.5469 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 4 | `biomarker:ki-67` | Ki-67 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5811 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 5 | `biomarker:tnf` | TNF-α | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5811 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 6 | `biomarker:vitamin-d` | Vitamin D | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5811 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 7 | `biomarker:mlh1` | MLH1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5002 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 8 | `biomarker:msh2` | MSH2 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5002 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 9 | `biomarker:msh6` | MSH6 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5002 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 10 | `biomarker:pms2` | PMS2 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5002 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 11 | `biomarker:pr` | PR | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5002 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 12 | `variant:egfr-t790m` | EGFR T790M | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.3834 | 2 publications indexed, no linked finding; no utility finding |
| 13 | `biomarker:il-1` | IL-1β | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.6145 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 14 | `biomarker:hcg` | β-hCG | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5349 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 15 | `gene:egfr` | EGFR gene | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4582 | 1 publications indexed, no linked finding; no utility finding |
| 16 | `biomarker:calcitonin` | Calcitonin | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4534 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 17 | `biomarker:crp` | CRP | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4534 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 18 | `biomarker:cystatin-c` | Cystatin C | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4534 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 19 | `biomarker:renal-egfr` | eGFR | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4534 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 20 | `biomarker:esr1` | ESR1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.4534 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
