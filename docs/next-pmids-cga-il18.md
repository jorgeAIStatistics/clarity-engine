# Next abstracts for CgA and IL-18

Candidates whose abstract text states a number next to the marker and a measure word. They were
found by a text filter (Europe PMC search plus a regex) and are not yet extracted or reviewed.
Do not re-run the qualitative abstracts already dead-lettered: 42196939, 41608640, 42095012,
42314925 (CgA) and 41976322, 42085057 (IL-18).

## Done (2026-09-15)

- **CgA, PMID 37951531**: 8 classification findings extracted (immunohistochemistry sensitivity in
  NEN and NEC); 4 link to chromogranin A. Two of those are panel sensitivities
  (synaptophysin + chromogranin A, ± INSM1) and should be reviewed before anyone reads them as
  CgA alone.

## Next

| Marker | PMID | Why it is a candidate |
|---|---|---|
| Chromogranin A | 42512273 | abstract states CgA with sensitivity/AUC and numbers |
| Chromogranin A | 42117183 | abstract states CgA with sensitivity/AUC and numbers |
| Chromogranin A | 40455177 | abstract states CgA with sensitivity/AUC and numbers |
| IL-18 | 38031068 | abstract states IL-18 with an association measure and a number |
| IL-18 | 38927536 | abstract states IL-18 with an association measure and a number |

Check that the numeric sentence is about the marker itself (42085057 failed because its
correlations were for other parameters), then extract once:
`evidence/intent_graph/jobs.py` or the observation extractor with that source.
