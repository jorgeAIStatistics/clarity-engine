"""Validated selected-source overlays; never overwrite cached clinical grades."""
import copy
import json
from pathlib import Path
from .provenance import validate_enrichment

OVERLAYS=json.loads(Path(__file__).with_name('intervention_enrichment.json').read_text())
validate_enrichment({'entities':list(OVERLAYS['profiles'].values())},json.loads(Path(__file__).with_name('source_snapshot.json').read_text()))

def enriched_profile(profile):
    import cache
    selected=OVERLAYS['profiles'].get(cache._slug(profile['name']))
    if not selected:return profile
    result=copy.deepcopy(profile)
    # Put selected extracts first so publication deduplication retains verified passages.
    result['claims']=[{'outcome':'Selected source extracts','studies':selected['studies']}]+result.get('claims',[])
    return result
