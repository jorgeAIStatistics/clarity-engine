"""A ranker that suggests work must not read its own label, rank a disease, or oversell itself."""
import unittest
from importlib.util import find_spec


@unittest.skipUnless(find_spec('sklearn'), 'the ranker is offline tooling; scikit-learn is not a web dependency')
class GapRankerTests(unittest.TestCase):
    def row(self, **kw):
        base = dict(id='biomarker:x', name='X', kind='Biomarker', aliases=3, entity_class=None,
                    findings=0, utility_findings=0, studies=0, asked=0, dead_letters=0)
        return {**base, **kw}

    def test_features_cannot_see_the_label(self):
        from ml.gap_ranker import FEATURES, features
        # findings and dead_letters decide the label, so they must not be inputs.
        self.assertNotIn('findings', FEATURES)
        self.assertNotIn('dead_letters', FEATURES)
        rich = self.row(findings=9, dead_letters=4, studies=2)
        poor = self.row(findings=0, dead_letters=0, studies=2)
        self.assertEqual(features(rich), features(poor))

    def test_labels_come_from_what_happened(self):
        from ml.gap_ranker import label
        self.assertEqual(label(self.row(findings=3)), 1)
        self.assertEqual(label(self.row(dead_letters=2)), 0)
        self.assertIsNone(label(self.row()), 'never attempted is not a negative')

    def test_a_weak_baseline_is_not_adopted(self):
        from ml.gap_ranker import fit_and_score
        # Labels unrelated to the features: no model should claim to rank this.
        rows = [self.row(id=f'biomarker:{i}', studies=i % 3, aliases=2 + i % 4, findings=i % 2, dead_letters=(i + 1) % 2) for i in range(20)]
        model, report = fit_and_score(rows)
        self.assertEqual(report['status'], 'fitted')
        self.assertFalse(report['useful'], f"random labels should not be useful: {report}")
        self.assertIn('majority_class_accuracy', report)

    def test_the_queue_skips_conditions_and_drugs_and_carries_its_reasons(self):
        from ml.gap_ranker import queue
        rows = [self.row(id='condition:breast-cancer', name='breast cancer', kind='Condition', studies=16),
                self.row(id='compound:olaparib', name='olaparib', kind='Compound', studies=4),
                self.row(id='biomarker:cea', name='CEA', kind='Biomarker', studies=5),
                self.row(id='test:amyloid-pet', name='amyloid PET', kind='Test')]
        ranked = queue(rows, None, {'useful': False}, limit=10)
        names = [r['name'] for r in ranked]
        self.assertNotIn('breast cancer', names)
        self.assertNotIn('olaparib', names)
        self.assertIn('CEA', names)
        self.assertTrue(all(r['reasons'] and r['baseline_adopted'] is False for r in ranked))
