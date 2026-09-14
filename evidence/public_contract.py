"""Guards applied to every intervention profile at the public API boundary.

Cached profiles in files and PostgreSQL are left untouched; each response is corrected
on the way out, so no cache rewrite or database migration is needed.

1. An interval the source did not report is never emitted. Legacy caches stored a
   placeholder interval (estimate ± |estimate − null|, i.e. [0, 2×estimate] for
   differences) flagged ci_estimated / is_estimated. The bounds are removed and the
   flag is kept, so existing consumers continue to withhold those estimates.
2. An exploratory pooled estimate is not emitted: pooling requires a registered
   synthesis plan and verified inputs, neither of which exists yet.
3. The legacy points score is not an evidence certainty, and its proportion-variance
   band is not a confidence interval. weighted_score is removed from public output.
"""
import copy

VERSION = 'public-contract-v1'
INTERVAL_NOTE = 'Interval not reported in the source; a previously estimated placeholder interval was removed.'
POOLING_NOTE = 'No pooled estimate: pooling requires a registered synthesis plan and verified inputs.'


def _walk(node, counts):
    if isinstance(node, list):
        for item in node:
            _walk(item, counts)
        return
    if not isinstance(node, dict):
        return
    if node.pop('weighted_score', None) is not None:
        counts['legacy_scores_removed'] += 1
    if node.get('ci_estimated') or node.get('is_estimated'):
        if node.get('ci_low') is not None or node.get('ci_high') is not None:
            counts['estimated_intervals_removed'] += 1
        node['ci_low'] = None
        node['ci_high'] = None
        node['interval_status'] = 'not_reported'
        node['interval_note'] = INTERVAL_NOTE
        if 'crosses_null' in node:
            node['crosses_null'] = None
    pooled = node.get('pooled')
    if isinstance(pooled, dict) and pooled.get('exploratory') is not None:
        pooled['exploratory'] = None
        pooled['note'] = POOLING_NOTE
        counts['exploratory_pools_removed'] += 1
    for value in node.values():
        _walk(value, counts)


def public_profile(profile):
    """Return a corrected deep copy of a cached or freshly generated profile."""
    if not isinstance(profile, dict):
        return profile
    result = copy.deepcopy(profile)
    counts = {'estimated_intervals_removed': 0, 'exploratory_pools_removed': 0, 'legacy_scores_removed': 0}
    _walk(result, counts)
    result['public_contract'] = {'version': VERSION, **counts}
    return result
