# Suggested extraction queue

Generated 2026-09-19T19:26:37Z by `python -m ml.gap_ranker`. Ranked by need: publications indexed but no typed finding, thin domains, and questions asked recently.

The learned baseline (gap-baseline-v1) **breaks ties** between entities the rule scores equally: leave-one-out accuracy 0.804 against a majority class of 0.569 on 51 attempts (AUC 0.749). It never sets the ranking: need does, because a model that predicts which attempt will succeed would rank the easy targets first and starve the real gaps.

Leave-one-out over 51 attempts. The interval on an accuracy from this many folds is wide; treat the comparison as a sanity check, not a measurement.

n_findings and n_utility are the counts the ranker read, so a row can be checked against the graph without rerunning anything. n_utility is the utility KIND, not the interventional layer: a trial of a drug is not evidence that measuring the marker helps.

| # | id | name | n_linked | n_primary | n_cited | n_utility | n_pubs | demand | need | baseline p | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `variant:alk-rearrangement` | ALK rearrangement | 0 | 0 | 0 | 0 | 5 | 0 | 5.0 | 0.6612 | 5 publications indexed, no linked finding; no utility finding |
| 2 | `biomarker:lp-a` | Lp(a) | 0 | 0 | 0 | 0 | 4 | 0 | 4.0 | 0.6937 | 4 publications indexed, no linked finding; no utility finding; no external identifier |
| 3 | `variant:egfr-l858r` | EGFR L858R | 0 | 0 | 0 | 0 | 4 | 0 | 4.0 | 0.6779 | 4 publications indexed, no linked finding; no utility finding |
| 4 | `biomarker:kras` | KRAS | 0 | 0 | 0 | 0 | 4 | 0 | 4.0 | 0.6538 | 4 publications indexed, no linked finding; no utility finding; no external identifier |
| 5 | `biomarker:ldh` | LDH | 0 | 0 | 0 | 0 | 4 | 0 | 4.0 | 0.6538 | 4 publications indexed, no linked finding; no utility finding; no external identifier |
| 6 | `variant:egfr-exon19-deletion` | EGFR exon 19 deletion | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6941 | 3 publications indexed, no linked finding; no utility finding |
| 7 | `biomarker:er` | ER | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6706 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 8 | `biomarker:hba1c` | HbA1c | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6706 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 9 | `biomarker:ca-15-3` | CA 15-3 | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6292 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 10 | `biomarker:ca-27-29` | CA 27.29 | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6292 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 11 | `biomarker:non-hdl-c` | non-HDL-C | 0 | 0 | 0 | 0 | 3 | 0 | 3.0 | 0.6292 | 3 publications indexed, no linked finding; no utility finding; no external identifier |
| 12 | `biomarker:ki-67` | Ki-67 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6466 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 13 | `biomarker:tnf` | TNF-α | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6466 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 14 | `biomarker:vitamin-d` | Vitamin D | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6466 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 15 | `biomarker:mlh1` | MLH1 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6039 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 16 | `biomarker:msh2` | MSH2 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6039 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 17 | `biomarker:msh6` | MSH6 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6039 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 18 | `biomarker:pms2` | PMS2 | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6039 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 19 | `biomarker:pr` | PR | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.6039 | 2 publications indexed, no linked finding; no utility finding; no external identifier |
| 20 | `variant:egfr-t790m` | EGFR T790M | 0 | 0 | 0 | 0 | 2 | 0 | 2.0 | 0.5414 | 2 publications indexed, no linked finding; no utility finding |
