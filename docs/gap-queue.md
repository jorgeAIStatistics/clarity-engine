# Suggested extraction queue

Generated 2026-09-18T19:48:06Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.804 against a majority class of 0.569 on 51 attempts (AUC 0.749). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 51 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

n_findings and n_utility are the counts the ranker read, so a row can be checked against the graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: a trial of a drug is not evidence that measuring the marker helps.

| # | id | name | n_findings | n_utility | n_pubs | need | baseline p | reason |
|---|---|---|---|---|---|---|---|---|
| 1 | `biomarker:lp-a` | Lp(a) | 0 | 0 | 4 | 3.25 | 0.6937 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 2 | `biomarker:er` | ER | 0 | 0 | 3 | 3.25 | 0.6706 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 3 | `biomarker:hba1c` | HbA1c | 0 | 0 | 3 | 3.25 | 0.6706 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 4 | `biomarker:il-1` | IL-1β | 0 | 0 | 1 | 3.25 | 0.6636 | 1 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 5 | `biomarker:kras` | KRAS | 0 | 0 | 4 | 3.25 | 0.6538 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 6 | `biomarker:ldh` | LDH | 0 | 0 | 4 | 3.25 | 0.6538 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 7 | `biomarker:ki-67` | Ki-67 | 0 | 0 | 2 | 3.25 | 0.6466 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 8 | `biomarker:tnf` | TNF-α | 0 | 0 | 2 | 3.25 | 0.6466 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 9 | `biomarker:vitamin-d` | Vitamin D | 0 | 0 | 2 | 3.25 | 0.6466 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 10 | `biomarker:ca-15-3` | CA 15-3 | 0 | 0 | 3 | 3.25 | 0.6292 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 11 | `biomarker:ca-27-29` | CA 27.29 | 0 | 0 | 3 | 3.25 | 0.6292 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 12 | `biomarker:non-hdl-c` | non-HDL-C | 0 | 0 | 3 | 3.25 | 0.6292 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 13 | `biomarker:hcg` | β-hCG | 0 | 0 | 1 | 3.25 | 0.6218 | 1 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 14 | `biomarker:mlh1` | MLH1 | 0 | 0 | 2 | 3.25 | 0.6039 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 15 | `biomarker:msh2` | MSH2 | 0 | 0 | 2 | 3.25 | 0.6039 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 16 | `biomarker:msh6` | MSH6 | 0 | 0 | 2 | 3.25 | 0.6039 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 17 | `biomarker:pms2` | PMS2 | 0 | 0 | 2 | 3.25 | 0.6039 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 18 | `biomarker:pr` | PR | 0 | 0 | 2 | 3.25 | 0.6039 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 19 | `biomarker:calcitonin` | Calcitonin | 0 | 0 | 1 | 3.25 | 0.5781 | 1 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 20 | `biomarker:crp` | CRP | 0 | 0 | 1 | 3.25 | 0.5781 | 1 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
