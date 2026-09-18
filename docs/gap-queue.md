# Suggested extraction queue

Generated 2026-09-18T19:34:58Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.775 against a majority class of 0.625 on 40 attempts (AUC 0.813). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 40 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

n_findings and n_utility are the counts the ranker read, so a row can be checked against the graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: a trial of a drug is not evidence that measuring the marker helps.

| # | id | name | n_findings | n_utility | n_pubs | need | baseline p | reason |
|---|---|---|---|---|---|---|---|---|
| 1 | `test:ctdna-liquid-biopsy` | ctDNA liquid biopsy | 0 | 0 | 1 | 4.5 | 0.2892 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 2 | `test:low-dose-ct-lung-screening` | low-dose CT lung cancer screening | 0 | 0 | 0 | 4.5 | 0.2426 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 3 | `precision_context:egfr-exon20-amivantamab` | EGFR exon 20 insertion NSCLC × amivantamab | 0 | 0 | 0 | 4.5 | 0.1929 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 4 | `precision_context:pik3ca-alpelisib` | PIK3CA-mutated breast cancer × alpelisib | 0 | 0 | 0 | 4.5 | 0.1929 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 5 | `biomarker:egfr` | EGFR | 0 | 0 | 16 | 3.25 | 0.9952 | 16 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 6 | `biomarker:her2` | HER2 | 0 | 0 | 12 | 3.25 | 0.988 | 12 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 7 | `biomarker:alk` | ALK | 0 | 0 | 7 | 3.25 | 0.9628 | 7 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 8 | `biomarker:cea` | CEA | 0 | 0 | 6 | 3.25 | 0.9535 | 6 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 9 | `biomarker:mmr` | MMR | 0 | 0 | 5 | 3.25 | 0.942 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 10 | `biomarker:tp53` | TP53 | 0 | 0 | 5 | 3.25 | 0.942 | 5 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 11 | `biomarker:kras` | KRAS | 0 | 0 | 4 | 3.25 | 0.9279 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 12 | `biomarker:ldh` | LDH | 0 | 0 | 4 | 3.25 | 0.9279 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 13 | `biomarker:lp-a` | Lp(a) | 0 | 0 | 4 | 3.25 | 0.9275 | 4 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 14 | `biomarker:ca-15-3` | CA 15-3 | 0 | 0 | 3 | 3.25 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 15 | `biomarker:ca-27-29` | CA 27.29 | 0 | 0 | 3 | 3.25 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 16 | `biomarker:non-hdl-c` | non-HDL-C | 0 | 0 | 3 | 3.25 | 0.9108 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 17 | `biomarker:er` | ER | 0 | 0 | 3 | 3.25 | 0.9102 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 18 | `biomarker:hba1c` | HbA1c | 0 | 0 | 3 | 3.25 | 0.9102 | 3 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 19 | `biomarker:mlh1` | MLH1 | 0 | 0 | 2 | 3.25 | 0.89 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
| 20 | `biomarker:msh2` | MSH2 | 0 | 0 | 2 | 3.25 | 0.89 | 2 linked publications but no typed finding; no interventional or guideline findings; no typed findings in any layer |
