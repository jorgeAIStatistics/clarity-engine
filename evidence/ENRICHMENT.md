# Selected-source depth pass — 2026-09-13

This release expands selected-source enrichment from 15 to 34 unique publications.
The 26 non-intervention profiles contain 56 reported finding rows; four intervention
routes expose nine additional rows (creatine aliases share one publication).
These are publication-linked extracts, not independent-trial counts, pooled results,
completed systematic reviews, or human-reviewed grades.

Priority additions: LDL-C (6 publications / 7 findings), HbA1c (2 / 4),
HER2–trastuzumab (2 / 3), MSI–pembrolizumab (2 / 3), Lp(a) (2 / 3),
ALK–alectinib (2 / 2), BRCA–olaparib (3 / 3), and adjuvant EGFR–osimertinib (2 / 4).
New precision profiles keep metastatic and adjuvant settings separate. Follow-up
publications share cohort IDs. ADAURA and J-ALEX retain nonstandard confidence levels.
Icosapent ethyl findings are not attributed to generic fish oil.

`source_snapshot.json` retains normalized Europe PMC/MEDLINE abstracts, source IDs,
retrieval dates and hashes. `catalog.json` and `intervention_enrichment.json` contain
quote spans and reported estimates. `provenance.py` validates identity, hashes,
quote offsets and numeric inclusion before export. Numeric inclusion is a consistency
check, not independent appraisal of an extraction. New records remain automated;
clinical grades and support/contradiction judgments are unchanged.

Intervention overlays are isolated from cached clinical grading. `enrichment.py`
adds selected passages to retrieval; the library deduplicates publication identities.
Frontend `SelectedExtracts` renders the validated static export. No additional paid
model calls or new services are introduced. Existing checkpointed monitoring and
review queues remain in place. Extraction dates never stand in for completed searches.

Export from the engine directory:

```sh
python3 -m evidence.export_catalog ../clarity-web/src/evidence/catalog.json
python3 -m evidence.library --output ../clarity-web/public/library.json
python3 -m unittest discover -s tests -q
```

Matcher v2 accepts text prepared from local CSV/TSV parsing. API limits remain
20–12,000 characters; no binary upload, saved queries or embeddings. Common identifier
and personal-health patterns are rejected before index construction. These guards
are not a de-identification system: only aggregate, non-identifying research content
is permitted. Matching returns relevance and source passages, never agreement grades.

## Question-depth pass — 2026-09-13

Selected enrichment now retains 38 unique publications and 64 non-intervention
finding rows, without adding empty entity profiles. New prediction records
PMID 22797450 and 31216866 add explicitly comparator-dependent C-index changes
across ApoB, LDL-C, non-HDL-C and Lp(a). The ApoB/apoA-I combination is not labeled
as ApoB alone. New ALK records PMID 32418886 and 35843080 retain ALEX and J-ALEX
settings, doses, crossover limitations, immature survival context and the reported
95.0405% confidence interval. Same-cohort reports are flagged for potential overlap.
All new extracts remain automated and pass source-span/hash/estimate validation.
