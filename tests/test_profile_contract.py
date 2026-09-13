import unittest
from evidence.profile import profile_contract,layer_for
from evidence.service import CATALOG
from living_research.triage import classify

class ProfileContractTests(unittest.TestCase):
    def test_layers_do_not_upgrade_unknown_or_animal_trials(self):
        self.assertEqual(layer_for({'design':'RCT','population':'animal'}),'preclinical')
        self.assertEqual(layer_for({'design':'RCT'}),'unclassified')
        self.assertEqual(layer_for({'design':'Meta-analysis','population':'human'}),'synthesis')
    def test_protocols_are_not_completed_trial_results(self):
        from classify import classify
        paper={'title':'Creatine: study protocol for a randomized trial','publication_types':['Randomized Controlled Trial'],'abstract':'We will recruit 100 adults.'}
        self.assertTrue(classify(paper)['is_review'])
        self.assertEqual(layer_for({**paper,'design':'RCT','population':'human'}),'protocol')
    def test_common_contract_retains_domain_frameworks(self):
        for entity in CATALOG['entities']:
            contract=profile_contract(entity,entity['entity_type'])
            self.assertEqual(contract['assessments'],entity['assessments'])
            self.assertIsNone(contract['freshness']['sources_checked_through'])
            self.assertFalse(contract['automatically_regraded'])
    def test_compound_dedup_and_generation_is_not_search_date(self):
        p={'name':'Example','generated_at':'2026-01-01','claims':[{'studies':[{'pmid':'1'}]},{'studies':[{'pmid':'1'}]}]}
        result=profile_contract(p)
        self.assertEqual(len(result['studies']),1)
        self.assertIsNone(result['freshness']['sources_checked_through'])
    def test_safety_prioritizes_review_without_declaring_clinical_impact(self):
        a=classify({'title':'Safety and mortality','publication_types':['Randomized Controlled Trial']},{})
        b=classify({'title':'Assay development'},{})
        self.assertGreater(a['impact_score'],b['impact_score'])
        self.assertFalse(a['clinical_impact_established'])
        self.assertEqual(b['relevance'],'awaiting_grounded_review')
