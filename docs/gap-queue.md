# Suggested extraction queue

Generated 2026-09-17T16:11:55Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.775 against a majority class of 0.625 on 40 attempts (AUC 0.813). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 40 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

| # | Entity | Kind | Need | Publications | Baseline p | Why |
|---|---|---|---|---|---|---|
| 1 | ctDNA liquid biopsy | Test | 4.5 | 1 | 0.2892 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 2 | low-dose CT lung cancer screening | Test | 4.5 | 0 | 0.2426 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 3 | EGFR exon 20 insertion NSCLC × amivantamab | PrecisionContext | 4.5 | 0 | 0.1929 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 4 | PIK3CA-mutated breast cancer × alpelisib | PrecisionContext | 4.5 | 0 | 0.1929 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 5 | EGFR | Biomarker | 3.25 | 16 | 0.9952 | 16 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 6 | HER2 | Biomarker | 3.25 | 12 | 0.988 | 12 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 7 | ALK | Biomarker | 3.25 | 7 | 0.9628 | 7 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 8 | CEA | Biomarker | 3.25 | 6 | 0.9535 | 6 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 9 | MMR | Biomarker | 3.25 | 5 | 0.942 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 10 | TP53 | Biomarker | 3.25 | 5 | 0.942 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 11 | KRAS | Biomarker | 3.25 | 4 | 0.9279 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 12 | LDH | Biomarker | 3.25 | 4 | 0.9279 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 13 | Lp(a) | Biomarker | 3.25 | 4 | 0.9275 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 14 | CA 15-3 | Biomarker | 3.25 | 3 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 15 | CA 27.29 | Biomarker | 3.25 | 3 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 16 | non-HDL-C | Biomarker | 3.25 | 3 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 17 | ER | Biomarker | 3.25 | 3 | 0.9102 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 18 | HbA1c | Biomarker | 3.25 | 3 | 0.9102 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 19 | MLH1 | Biomarker | 3.25 | 2 | 0.89 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 20 | MSH2 | Biomarker | 3.25 | 2 | 0.89 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
