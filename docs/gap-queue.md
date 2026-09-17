# Suggested extraction queue

Generated 2026-09-17T15:56:27Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.750 against a majority class of 0.656 on 32 attempts (AUC 0.706). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 32 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

| # | Entity | Kind | Need | Publications | Baseline p | Why |
|---|---|---|---|---|---|---|
| 1 | faecal calprotectin testing | Test | 4.5 | 0 | 0.2955 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 2 | HPV cervical screening | Test | 4.5 | 0 | 0.2955 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 3 | low-dose CT lung cancer screening | Test | 4.5 | 0 | 0.2955 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 4 | natriuretic peptide testing for heart failure | Test | 4.5 | 0 | 0.2955 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 5 | ctDNA liquid biopsy | Test | 4.5 | 1 | 0.2874 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 6 | D-dimer for pulmonary embolism | Test | 4.5 | 0 | 0.2687 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 7 | HER2-low breast cancer × trastuzumab deruxtecan | PrecisionContext | 4.5 | 2 | 0.2378 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 8 | PD-L1 high NSCLC × pembrolizumab | PrecisionContext | 4.5 | 0 | 0.2057 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 9 | ROS1 fusion NSCLC × entrectinib | PrecisionContext | 4.5 | 0 | 0.2057 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 10 | EGFR exon 20 insertion NSCLC × amivantamab | PrecisionContext | 4.5 | 0 | 0.1849 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 11 | PIK3CA-mutated breast cancer × alpelisib | PrecisionContext | 4.5 | 0 | 0.1849 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 12 | EGFR | Biomarker | 3.25 | 16 | 0.9159 | 16 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 13 | HER2 | Biomarker | 3.25 | 12 | 0.8521 | 12 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 14 | ALK | Biomarker | 3.25 | 7 | 0.7834 | 7 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 15 | CEA | Biomarker | 3.25 | 6 | 0.7672 | 6 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 16 | Lp(a) | Biomarker | 3.25 | 4 | 0.7574 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 17 | MMR | Biomarker | 3.25 | 5 | 0.7502 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 18 | TP53 | Biomarker | 3.25 | 5 | 0.7502 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 19 | ER | Biomarker | 3.25 | 3 | 0.7399 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 20 | HbA1c | Biomarker | 3.25 | 3 | 0.7399 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
