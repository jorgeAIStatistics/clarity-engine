# Suggested extraction queue

Generated 2026-09-16T19:52:36Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) is **not adopted**: leave-one-out accuracy 0.727 against a majority class of 0.773 on 22 attempts. Its probability is shown for comparison only.

| # | Entity | Kind | Need | Publications | Baseline p | Why |
|---|---|---|---|---|---|---|
| 1 | ApoB | Biomarker | 9.25 | 5 | 0.3233 | 5 linked publications but no typed finding; asked in 3 recent questions; no interventional or guideline findings; no typed findings in any layer |
| 2 | LDL-C | Biomarker | 9.25 | 9 | 0.7528 | 9 linked publications but no typed finding; asked in 3 recent questions; no interventional or guideline findings; no typed findings in any layer |
| 3 | ALK-positive NSCLC × alectinib | PrecisionContext | 4.5 | 0 | 0.1168 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 4 | amyloid PET imaging | Test | 4.5 | 0 | 0.2774 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 5 | BRAF V600E melanoma × dabrafenib and trametinib | PrecisionContext | 4.5 | 0 | 0.1168 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 6 | BRCA-mutated ovarian cancer × olaparib maintenance | PrecisionContext | 4.5 | 0 | 0.0822 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 7 | CT colonography | Test | 4.5 | 0 | 0.2064 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 8 | ctDNA liquid biopsy | Test | 4.5 | 0 | 0.2064 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 9 | D-dimer for pulmonary embolism | Test | 4.5 | 0 | 0.2064 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 10 | EGFR exon 20 insertion NSCLC × amivantamab | PrecisionContext | 4.5 | 0 | 0.0822 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
| 11 | faecal calprotectin testing | Test | 4.5 | 0 | 0.2774 | thin domain: test; no interventional or guideline findings; no typed findings in any layer |
| 12 | HER2-low breast cancer × trastuzumab deruxtecan | PrecisionContext | 4.5 | 0 | 0.1168 | thin domain: precision pair; no interventional or guideline findings; no typed findings in any layer |
