"""Deterministic, quote-backed synthesis proposals; never a new clinical grade.

A proposal combines reviewed evidence with one candidate without pooling unlike
outcomes or passing model prose off as a systematic review.
"""
VERSION = 'layered-synthesis-v1'
LAYER_NAMES = ('human', 'animal', 'in_vitro', 'mixed', 'unknown')

def build_synthesis(proposal, baseline, threshold=40):
    facts = proposal.get('extraction', {}).get('facts', {})
    triage = proposal.get('triage', {})
    reasons = list(triage.get('reasons', []))
    if facts.get('relevance', {}).get('value') != 'direct':
        return {'version': VERSION, 'status': 'deferred', 'reason': 'Direct relevance has not been established'}
    if triage.get('impact_score', 0) < threshold:
        return {'version': VERSION, 'status': 'deferred', 'reason': 'Below synthesis impact threshold'}
    if not facts.get('outcomes'):
        return {'version': VERSION, 'status': 'deferred', 'reason': 'No quote-backed outcome extracted'}
    layers = {key: [] for key in LAYER_NAMES}
    paper = proposal['paper']
    entries = [u for u in baseline.get('updates', []) if u['paper_id'] != proposal['paper_id']]
    entries.append({'paper_id': proposal['paper_id'], 'paper': paper, 'facts': facts, 'candidate': True})
    for entry in entries:
        entry_facts = entry.get('facts', {})
        layer = entry_facts.get('population_layer', {}).get('value', 'unknown')
        if layer not in layers: layer = 'unknown'
        # Keep each finding attached to its own population, outcome and source.
        layers[layer].append({'paper_id': entry['paper_id'], 'source_url': entry['paper']['url'],
            'pmid': entry['paper'].get('pmid'), 'candidate': entry.get('candidate', False),
            'is_preprint': bool(entry['paper'].get('is_preprint')),
            'is_registration': bool(entry['paper'].get('nct_id')), 'facts': entry_facts})
    return {'version': VERSION, 'status': 'review_required', 'baseline_version': baseline.get('version', 0),
        'impact_score': triage['impact_score'], 'impact_reasons': reasons, 'layers': layers,
        'affected_dimensions': proposal.get('affected_dimensions', []),
        'clinical_grade_changed': False, 'method': 'Source-linked assembly; no numerical pooling or causal inference',
        'limitations': ['Candidate evidence is unreviewed.', 'This collection is not a complete systematic review.',
                       'Unreported study details and formal risk of bias remain unresolved.']}
