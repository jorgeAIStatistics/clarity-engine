import unittest
from living_research.synthesis import build_synthesis
from living_research.extraction import validate_extraction, source_text
from production import commands

class SynthesisTests(unittest.TestCase):
    def proposal(self):
        return {'paper_id':'pmid:1','paper':{'url':'https://pubmed.ncbi.nlm.nih.gov/1/','pmid':'1'},
          'triage':{'impact_score':40,'reasons':['New trial']},'extraction':{'facts':{
            'relevance':{'value':'direct'},'population_layer':{'value':'human'},'outcomes':{'value':'Survival','quote':'Survival measured'}}}}
    def test_threshold_does_not_publish_or_pool(self):
        proposal=self.proposal()
        result=build_synthesis(proposal,{'version':2,'updates':[]})
        self.assertEqual(result['status'],'review_required')
        self.assertFalse(result['clinical_grade_changed'])
        self.assertTrue(result['layers']['human'][0]['candidate'])
        self.assertEqual(result['baseline_version'],2)
        proposal['triage']['impact_score']=39
        self.assertEqual(build_synthesis(proposal,{})['status'],'deferred')
    def test_uncertain_relevance_cannot_change_synthesis(self):
        proposal=self.proposal();proposal['extraction']['facts']['relevance']['value']='uncertain'
        self.assertEqual(build_synthesis(proposal,{})['status'],'deferred')
    def test_separate_evidence_layers(self):
        baseline={'updates':[{'paper_id':'pmid:2','paper':{'url':'https://example.org'},'facts':{'population_layer':{'value':'animal'}}}]}
        result=build_synthesis(self.proposal(),baseline)
        self.assertEqual(len(result['layers']['human']),1)
        self.assertEqual(len(result['layers']['animal']),1)
    def test_source_spans_reconstruct_quotes(self):
        paper={'title':'Study','abstract':'Measured in 100 adults.','url':'https://example.org'}
        fact=validate_extraction({'population':{'value':'100 adults','quote':'Measured in 100 adults.'}},paper)['population']
        span=fact['source_span']
        self.assertEqual(source_text(paper)[span['start']:span['end']],fact['quote'])
    def test_production_requires_durable_state(self):
        self.assertEqual(len(commands({})),1)
        self.assertEqual(len(commands({'DATABASE_URL':'postgresql://db'})),2)
        self.assertNotIn('--llm',commands({'DATABASE_URL':'postgresql://db'})[1])
        self.assertIn('--llm',commands({'DATABASE_URL':'postgresql://db','ANTHROPIC_API_KEY':'present'})[1])
        self.assertEqual(len(commands({'DATABASE_URL':'postgresql://db','CLARITY_RESEARCH_ENABLED':'0'})),1)
    def test_priority_ages_and_bounds_traffic(self):
        from living_research.priority import priority_score
        self.assertGreater(priority_score({'next_due':1},864001),priority_score({'next_due':864001},864001))
        self.assertEqual(priority_score({'monthly_views':float('nan')},0),priority_score({},0))
        self.assertLess(priority_score({'monthly_views':1e20,'recent_publications':1e20},0),100)
    def test_protocol_does_not_get_trial_priority(self):
        from living_research.triage import classify
        result=classify({'title':'Study protocol for a randomized trial','publication_types':['Randomized Controlled Trial']},{})
        self.assertEqual(result['study_type_candidate'],'study_protocol')
        self.assertFalse(result['synthesis_eligible'])
