import json
import re
import unittest
from pathlib import Path
from evidence.public_contract import public_profile
from evidence.analysis import analyse_profile

ROOT = Path(__file__).resolve().parent.parent


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


class PublicContractTests(unittest.TestCase):
    def test_estimated_bounds_removed_reported_bounds_kept(self):
        cached = {'name': 'Example', 'weighted_score': {'score': 89.0}, 'claims': [{
            'outcome': 'muscle strength',
            'headline_effect': {'metric': 'mean_diff', 'value': 4.43, 'ci_low': 0.0, 'ci_high': 8.86, 'ci_estimated': True, 'crosses_null': False},
            'effects': {'plottable': [
                {'pmid': '1', 'metric': 'mean_diff', 'value': 0.94, 'ci_low': 0.0, 'ci_high': 1.88, 'ci_estimated': True, 'status': 'derived'},
                {'pmid': '2', 'metric': 'hr', 'value': 0.54, 'ci_low': 0.43, 'ci_high': 0.67, 'ci_estimated': False, 'status': 'verified'}]},
            'pooled': {'verified': None, 'exploratory': {'value': 1.2}, 'note': ''},
            'weighted_score': {'final_score': 90.5, 'confidence_interval': {'lower': 70.2, 'upper': 100.0}, 'confidence_tier': 'Gold Standard'},
        }]}
        served = public_profile(cached)
        claim = served['claims'][0]
        self.assertEqual((claim['headline_effect']['ci_low'], claim['headline_effect']['ci_high']), (None, None))
        self.assertTrue(claim['headline_effect']['ci_estimated'])
        self.assertIsNone(claim['headline_effect']['crosses_null'])
        self.assertEqual(claim['headline_effect']['interval_status'], 'not_reported')
        plotted = claim['effects']['plottable']
        self.assertIsNone(plotted[0]['ci_low'])
        self.assertEqual((plotted[1]['ci_low'], plotted[1]['ci_high']), (0.43, 0.67))
        self.assertIsNone(claim['pooled']['exploratory'])
        self.assertNotIn('weighted_score', claim)
        self.assertNotIn('weighted_score', served)
        self.assertEqual(served['public_contract']['estimated_intervals_removed'], 2)
        self.assertEqual(served['public_contract']['legacy_scores_removed'], 2)
        self.assertEqual(cached['claims'][0]['headline_effect']['ci_low'], 0.0, 'input must not be mutated')

    def test_no_cached_profile_serves_unreported_interval_or_legacy_score(self):
        checked = 0
        for path in sorted((ROOT / 'cache').glob('*.json')):
            profile = json.loads(path.read_text())
            if not isinstance(profile, dict) or not profile.get('claims'):
                continue
            served = public_profile(profile)
            checked += 1
            text = json.dumps(served)
            self.assertNotIn('confidence_tier', text, path.name)
            for node in nodes(served):
                self.assertNotIn('weighted_score', node, path.name)
                if node.get('ci_estimated') or node.get('is_estimated'):
                    self.assertIsNone(node.get('ci_low'), path.name)
                    self.assertIsNone(node.get('ci_high'), path.name)
                low, high, value = node.get('ci_low'), node.get('ci_high'), node.get('value')
                if isinstance(low, (int, float)) and isinstance(high, (int, float)) and isinstance(value, (int, float)) and value and low == 0 and abs(high - 2 * value) < 1e-9:
                    # A source can genuinely report such an interval (iodine: "β = 0.05, 0.00-0.10");
                    # a placeholder is one whose bounds do not occur in its quote.
                    reported = {float(n) for n in re.findall(r'(?<![\d.])\d+(?:\.\d+)?', str(node.get('quote') or ''))}
                    self.assertTrue({float(low), float(high)} <= reported, f'{path.name}: [0, 2×estimate] interval not present in its source quote')
            analyse_profile(served)
        self.assertGreater(checked, 100)


if __name__ == '__main__':
    unittest.main()
