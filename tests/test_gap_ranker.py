"""A ranker that suggests work must not read its own label, rank a disease, or oversell itself."""
import unittest
from importlib.util import find_spec


@unittest.skipUnless(find_spec('sklearn'), 'the ranker is offline tooling; scikit-learn is not a web dependency')
class GapRankerTests(unittest.TestCase):
    def row(self, **kw):
        # Mirrors ml.gap_ranker.ROWS: utility_findings is the interventional/guidelines LAYER count
        # the need rule words its reasons from, utility_kind_findings the utility KIND the queue
        # reports. Keeping both is the point — they answer different questions.
        # Mirrors cypher.GAP_FEATURES, the one definition the exporter and the ranker share.
        base = dict(id='biomarker:x', name='X', kind='Biomarker', aliases=3, entity_class=None,
                    n_findings_linked=0, n_primary=0, n_cited=0, n_unclear=0, n_utility=0,
                    n_discrimination=0, n_classification=0, n_trial_layer=0,
                    n_pubs=0, matcher_demand=0, dead_letters=0, has_ids=False)
        return {**base, **kw}

    def test_features_cannot_see_the_label(self):
        from ml.gap_ranker import FEATURES, features
        # findings and dead_letters decide the label, so they must not be inputs.
        self.assertNotIn('n_findings_linked', FEATURES)
        self.assertNotIn('n_cited', FEATURES)
        self.assertNotIn('dead_letters', FEATURES)
        rich = self.row(n_findings_linked=9, dead_letters=4, n_pubs=2)
        poor = self.row(n_findings_linked=0, dead_letters=0, n_pubs=2)
        self.assertEqual(features(rich), features(poor))

    def test_labels_come_from_what_happened(self):
        from ml.gap_ranker import label
        self.assertEqual(label(self.row(n_findings_linked=3)), 1)
        self.assertEqual(label(self.row(dead_letters=2)), 0)
        self.assertIsNone(label(self.row()), 'never attempted is not a negative')

    def test_a_weak_baseline_is_not_adopted(self):
        from ml.gap_ranker import fit_and_score
        # Labels unrelated to the features: no model should claim to rank this.
        rows = [self.row(id=f'biomarker:{i}', n_pubs=i % 3, aliases=2 + i % 4, n_findings_linked=i % 2, dead_letters=(i + 1) % 2) for i in range(20)]
        model, report = fit_and_score(rows)
        self.assertEqual(report['status'], 'fitted')
        self.assertFalse(report['useful'], f"random labels should not be useful: {report}")
        self.assertIn('majority_class_accuracy', report)

    def test_the_queue_skips_conditions_and_drugs_and_carries_its_reasons(self):
        from ml.gap_ranker import queue
        rows = [self.row(id='condition:breast-cancer', name='breast cancer', kind='Condition', n_pubs=16),
                self.row(id='compound:olaparib', name='olaparib', kind='Compound', n_pubs=4),
                self.row(id='biomarker:cea', name='CEA', kind='Biomarker', n_pubs=5),
                self.row(id='test:amyloid-pet', name='amyloid PET', kind='Test', n_pubs=1)]
        ranked = queue(rows, None, {'useful': False}, limit=10)
        names = [r['name'] for r in ranked]
        self.assertNotIn('breast cancer', names)
        self.assertNotIn('olaparib', names)
        self.assertIn('CEA', names)
        # Nothing indexed and nobody asking is not a gap worth a call: there is nothing to read.
        self.assertEqual(queue([self.row(id='biomarker:quiet', name='Quiet', n_pubs=0)], None, {}, limit=5), [])
        # An entity whose utility rung is already filled drops out however much else it has.
        self.assertEqual(queue([self.row(id='biomarker:done', name='Done', n_pubs=20, n_utility=1)], None, {}, limit=5), [])
        self.assertTrue(all(r['reasons'] and r['baseline_breaks_ties'] is False for r in ranked))

    def test_the_baseline_only_ever_breaks_a_tie(self):
        from ml.gap_ranker import queue
        """Need is the ranking. A model that predicts which attempt succeeds would rank the easy
        targets first and starve the gaps, so it is allowed to order equals and nothing more."""
        rows = [self.row(id='biomarker:a', name='Aaa', n_pubs=2), self.row(id='biomarker:b', name='Bbb', n_pubs=2)]

        import numpy as np

        class Likely:
            """Says the second entity is the likelier attempt, and nothing about the first."""
            def predict_proba(self, X):
                return np.array([[0.1, 0.9] if i else [0.9, 0.1] for i in range(len(X))])

        tied = queue(rows, Likely(), {'useful': True}, limit=10)
        self.assertEqual([r['name'] for r in tied], ['Bbb', 'Aaa'], 'the likelier of two equals goes first')
        self.assertEqual([r['score'] for r in tied][0], tied[1]['score'], 'and only because they tie on need')
        self.assertTrue(all(r['model'] == 'rule-need-v2' for r in tied), 'the stored ranking is still the rule')
        ignored = queue(rows, Likely(), {'useful': False}, limit=10)
        self.assertEqual([r['name'] for r in ignored], ['Aaa', 'Bbb'], 'an unproven baseline changes nothing')
