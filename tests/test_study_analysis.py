import copy
import unittest
from evidence.analysis import analyse_effect,analyse_profile,context_signals

SOURCE={'pmid':'123','title':'Trial in healthy adults','design':'RCT','population':'human','url':'https://pubmed.ncbi.nlm.nih.gov/123/','abstract':'A mean difference of 0.68 kg (95% CI 0.26 to 1.11) was reported after 12 weeks at 5 g/day.'}
EFFECT={'pmid':'123','metric':'mean_diff','value':.68,'ci_low':.26,'ci_high':1.11,'status':'verified','quote':SOURCE['abstract']}

class StudyAnalysisTests(unittest.TestCase):
    def test_native_units_and_interpretation(self):
        effect=analyse_effect(EFFECT,{'123':SOURCE})
        self.assertTrue(effect['eligible']);self.assertEqual(effect['unit'],'kg')
        self.assertEqual(effect['interval_level'],95);self.assertFalse(effect['crosses_null'])
        self.assertNotIn('improves',effect['interpretation'])
    def test_credible_is_not_confidence_and_crossing_is_not_no_effect(self):
        e={**EFFECT,'metric':'smd','value':.11,'ci_low':-.02,'ci_high':.25,'quote':'Estimate 0.11 (95% Credible Interval: -0.02 to 0.25)'}
        result=analyse_effect(e,{'123':SOURCE})
        self.assertEqual(result['interval_kind'],'credible interval');self.assertTrue(result['crosses_null'])
        self.assertIn('does not demonstrate equivalence',result['interpretation'])
    def test_derived_sign_mismatched_and_unknown_sources_are_withheld(self):
        for change in ({'ci_estimated':True},{'converted':True},{'status':'derived'},{'ci_low':-.26},{'pmid':'999'},{'value':float('nan')}):
            self.assertFalse(analyse_effect({**EFFECT,**change},{'123':SOURCE})['eligible'])
    def test_protocol_and_preprint_are_not_results(self):
        for change in ({'title':'Study protocol: randomized creatine trial'},{'is_preprint':True}):
            self.assertFalse(analyse_effect(EFFECT,{'123':{**SOURCE,**change}})['eligible'])
    def test_source_identity_and_duplicate_effects_not_double_counted(self):
        profile={'name':'Example','claims':[{'outcome':'Strength','studies':[SOURCE,SOURCE],'effects':{'plottable':[EFFECT,EFFECT]}}]}
        before=copy.deepcopy(profile);result=analyse_profile(profile)
        self.assertEqual(result['coverage']['linked_studies'],1)
        self.assertEqual(len(result['outcomes'][0]['effects']),1)
        self.assertEqual(before,profile)
        self.assertNotIn('pooled',result['outcomes'][0])
    def test_exact_context_spans(self):
        source=SOURCE['title']+'\n'+SOURCE['abstract']
        for facts in context_signals(SOURCE).values():
            for fact in facts:self.assertEqual(source[fact['start']:fact['end']],fact['text'])
    def test_ratio_null_is_one(self):
        e={**EFFECT,'metric':'hr','value':.8,'ci_low':.64,'ci_high':1,'quote':'HR 0.8 (95% CI 0.64 to 1.0)'}
        result=analyse_effect(e,{'123':SOURCE})
        self.assertEqual(result['null'],1);self.assertIn('boundary',result['interpretation'])

    def test_quartiles_are_not_confidence_intervals(self):
        effect={**EFFECT,'value':15.25,'ci_low':10.57,'ci_high':19.68,'quote':'+15.25 ng/mL (p25 = 10.57; p75 = 19.68)'}
        self.assertFalse(analyse_effect(effect,{'123':SOURCE})['eligible'])
    def test_within_group_and_metric_conflicts_are_withheld(self):
        for change in [dict(quote='mean change 0.68 (95% CI 0.26 to 1.11) in the intervention group'),dict(metric='or',quote='RR 0.68 (95% CI 0.26 to 1.11)')]:
            self.assertFalse(analyse_effect({**EFFECT,**change},{'123':SOURCE})['eligible'])
