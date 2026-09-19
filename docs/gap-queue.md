# Suggested extraction queue

Generated 2026-09-19T20:10:35Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.812 against a majority class of 0.641 on 64 attempts (AUC 0.811). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 64 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

n_findings and n_utility are the counts the ranker read, so a row can be checked against the graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: a trial of a drug is not evidence that measuring the marker helps.

| # | id | name | n_linked | n_primary | n_cited | n_unclear | n_utility | n_pubs | demand | need | baseline p | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `biomarker:vitamin-d` | Vitamin D | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6443 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 2 | `biomarker:mlh1` | MLH1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5666 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 3 | `biomarker:msh2` | MSH2 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5666 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 4 | `biomarker:msh6` | MSH6 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5666 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 5 | `biomarker:pms2` | PMS2 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5666 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 6 | `biomarker:pr` | PR | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5666 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 7 | `variant:egfr-t790m` | EGFR T790M | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.3434 | 2 publications indexed, no linked finding; no utility finding |
| 8 | `biomarker:il-1` | IL-1β | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.6637 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 9 | `biomarker:hcg` | β-hCG | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5875 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 10 | `biomarker:calcitonin` | Calcitonin | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 11 | `biomarker:crp` | CRP | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 12 | `biomarker:cystatin-c` | Cystatin C | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 13 | `biomarker:renal-egfr` | eGFR | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 14 | `biomarker:esr1` | ESR1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 15 | `biomarker:gfap` | GFAP | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 16 | `biomarker:her3` | HER3 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 17 | `biomarker:met` | MET | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 18 | `biomarker:mgmt` | MGMT | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 19 | `biomarker:nras` | NRAS | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
| 20 | `biomarker:pik3ca` | PIK3CA | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1.0 | 0.5069 | 1 publications indexed, no linked finding; no utility finding; no external identifier |
