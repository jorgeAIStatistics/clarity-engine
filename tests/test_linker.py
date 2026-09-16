"""The linker may never buy robustness with a hijack. These lock both ends of that trade."""
import json
import unittest
from importlib.util import find_spec
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / 'evidence' / 'intent_graph' / 'registry.json'


@unittest.skipUnless(find_spec('sklearn'), 'the linker is offline tooling; scikit-learn is not a web dependency')
class LinkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ml.linker import AliasIndex, evaluate
        cls.nodes = json.loads(REGISTRY.read_text())
        cls.index = AliasIndex(cls.nodes)
        cls.report = evaluate()

    def link(self, span):
        hit = self.index.best(span)
        return hit[0] if hit else None

    def test_gold_set_is_perfect_and_free_of_hijacks(self):
        gold = self.report['gold']
        self.assertEqual((gold['precision'], gold['recall'], gold['hijacks']), (1.0, 1.0, []))
        self.assertGreaterEqual(gold['cases'], 23)

    def test_it_beats_exact_matching_on_spelling_and_spacing(self):
        robustness = self.report['robustness']
        self.assertEqual(robustness['linker_matches'], robustness['cases'])
        self.assertLess(robustness['exact_alias_matches'], robustness['cases'], 'otherwise the linker earns nothing')

    def test_case_is_identity_for_an_acronym(self):
        # eGFR is kidney function; EGFR is a receptor. Lowercasing both is how pages get hijacked.
        self.assertEqual(self.link('eGFR'), 'biomarker:renal-egfr')
        self.assertEqual(self.link('EGFR'), 'biomarker:egfr')
        from ml.linker import resolve_question
        kidney = resolve_question(self.index, 'eGFR and cystatin C as predictors of kidney function decline', self.nodes)
        self.assertIn('biomarker:renal-egfr', kidney)
        self.assertNotIn('biomarker:egfr', kidney, 'the receptor must not answer a kidney question')

    def test_punctuation_and_spacing_are_not_identity(self):
        for span, expected in [('CA 125', 'biomarker:ca-125'), ('CA-19-9', 'biomarker:ca19-9'),
                               ('NT pro BNP', 'biomarker:nt-probnp'), ('p-tau 181', 'biomarker:p-tau181')]:
            self.assertEqual(self.link(span), expected, span)

    def test_a_shared_ordinary_word_attaches_nothing(self):
        from ml.linker import resolve_question
        # "associated", "mutation" and "screening" appear in aliases but name no-one on their own.
        for question, forbidden in [('Is IL18 associated with pain after radiotherapy?', 'biomarker:bap1'),
                                    ('MGMT methylation and IDH1 mutation in glioma', 'variant:egfr-activating-mutation'),
                                    ('PSA concentration and screening for prostate cancer', 'test:low-dose-ct-lung-screening')]:
            self.assertNotIn(forbidden, resolve_question(self.index, question, self.nodes), question)

    def test_a_short_name_is_not_swallowed_by_a_longer_one(self):
        from ml.linker import resolve_question, inside
        found = resolve_question(self.index, 'Ki-67 and ER expression in breast cancer', self.nodes)
        self.assertIn('biomarker:er', found, 'ER is not inside "breast cancer"')
        self.assertTrue(inside('EGFR', 'EGFR mutation'))
        self.assertFalse(inside('ER', 'breast cancer'))

    def test_the_il18_title_still_attaches_nothing_from_breast_cancer_fame(self):
        from ml.linker import resolve_question
        found = resolve_question(self.index, 'Interleukin-18 as a Potential Biomarker for Radiotherapy-Related Pain in Breast Cancer: Implications for Personalized Pain Management', self.nodes)
        self.assertIn('biomarker:il-18', found)
        for celebrity in ('gene:brca1', 'gene:brca2', 'biomarker:her2', 'compound:olaparib', 'compound:trastuzumab', 'test:mammography'):
            self.assertNotIn(celebrity, found)
