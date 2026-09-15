import unittest
from evidence.matcher import documents,match,passage,expanded_tokens
class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.index=documents([{'id':'apob','entity_type':'biomarker','name':'ApoB','aliases':['apolipoprotein B'],'summary':'Atherogenic particle measurement','outcomes':[{'name':'Cardiovascular events'}], 'studies':[{'pmid':'1','title':'ApoB cardiovascular risk','abstract':'ApoB was measured in adults. Risk was associated with ApoB.','population':'human','study_type':'observational'}]}, {'id':'psa','entity_type':'biomarker','name':'PSA','aliases':[],'outcomes':[],'studies':[]}])
    def test_alias_retrieval_and_source_provenance(self):
        result=match('We studied apolipoprotein B and cardiovascular events.',self.index)
        self.assertEqual(result['entities'][0]['id'],'entity:apob')
        source=result['studies'][0];span=source['passage'];original=self.index[1][0]['_text']
        self.assertEqual(original[span['start']:span['end']],span['text'])
        self.assertEqual(source['agreement'],'not_assessed');self.assertFalse(result['query_stored'])
    def test_no_false_agreement(self):
        result=match('ApoB was not associated with cardiovascular events.',self.index)
        self.assertEqual(result['agreement_assessment']['supporting'],[])
        self.assertEqual(result['agreement_assessment']['contradicting'],[])
    def test_empty_unmatched_and_limits(self):
        self.assertRaises(ValueError,match,'short',self.index)
        self.assertRaises(ValueError,match,'a'*12001,self.index)
        result=match('quasar telescope galactic astronomy',self.index)
        self.assertEqual(result['entities'],[]);self.assertEqual(result['studies'],[])
    def test_concept_expansion(self):
        self.assertIn('glycated',expanded_tokens('HbA1c measurement'))
    def test_endpoint_rejects_unbounded_payload(self):
        from flask import Flask
        from evidence.routes import blueprint
        app=Flask(__name__);app.register_blueprint(blueprint)
        self.assertEqual(app.test_client().post('/api/evidence/match',json={'text':'a'*12001}).status_code,400)

    def test_passage_preserves_decimal_numbers(self):
        text='The difference was 0.25 kg (p<0.05). A second sentence.'
        self.assertEqual(passage(text,{'difference'})['text'],'The difference was 0.25 kg (p<0.05).')

class ResearchScopeTests(unittest.TestCase):
    def test_personal_input_rejected_before_retrieval(self):
        from evidence.matcher import match,research_input_error
        for query in ['patient_id,Marker\n12345,ApoB','Here are my blood test results: LDL 150','email: test@example.com in this table']:
            self.assertTrue(research_input_error(query))
            with self.assertRaises(ValueError):match(query,([],[]))
    def test_research_descriptions_allowed(self):
        from evidence.matcher import research_input_error
        self.assertFalse(research_input_error('Aggregate HbA1c results in a cohort of patients with diabetes'))
    def test_oncology_table_does_not_rank_renal_egfr_first(self):
        from evidence.matcher import documents,match
        from evidence.service import CATALOG
        result=match('topic: EGFR; context: resected lung cancer; outcome: disease-free survival',documents(CATALOG['entities']))
        self.assertNotEqual(result['entities'][0]['id'],'entity:creatinine-egfr')
        self.assertEqual(result['entities'][0]['entity_type'],'precision_oncology')
        self.assertTrue(any('hazard ratio' in s['passage']['text'].lower() for s in result['studies']))

class LayerCoverageTests(unittest.TestCase):
    def setUp(self):
        abstract='Higher ApoB was associated with events (hazard ratio 1.20, 95% CI 1.10-1.30).'
        trial='Treatment lowered events (hazard ratio 0.85, 95% CI 0.78-0.93).'
        null='Walking distance did not differ (mean difference -0.5, 95% CI -1.2 to 0.2).'
        def finding(outcome,measure,estimate,lower,upper,quote):
            return {'outcome':outcome,'effect':{'measure':measure,'estimate':estimate,'lower':lower,'upper':upper,'origin':'reported'},'quote':quote}
        studies=[
            {'pmid':'11','year':'2021','title':'ApoB cohort','abstract':abstract,'design':'Prospective cohort','population':'Human; adults','findings':[finding('Cardiovascular events','hazard ratio',1.2,1.1,1.3,abstract)]},
            {'pmid':'12','year':'2023','title':'ApoB lowering trial','abstract':trial,'design':'Randomized controlled trial','population':'Human; adults','review_status':'reviewed','findings':[finding('Cardiovascular events','hazard ratio',0.85,0.78,0.93,trial)]},
            {'pmid':'17','year':'2019','title':'Second trial','abstract':null,'design':'Randomized controlled trial','population':'Human; adults','findings':[finding('Walking distance','mean difference',-0.5,-1.2,0.2,null)]},
            {'pmid':'13','year':'2020','title':'ApoB in mice','abstract':'Mice.','design':'Animal study','population':'mice'},
            {'pmid':'14','year':'2022','title':'ApoB meta-analysis','abstract':'Pooled.','design':'Systematic review and meta-analysis','population':'Human'},
            {'pmid':'15','year':'2024','title':'Lipid guideline','abstract':'Guidance.','design':'Clinical practice guideline','population':'Human'},
            {'pmid':'16','year':'2025','title':'Planned ApoB trial','abstract':'Protocol.','design':'Trial protocol','population':'Human'},
        ]
        self.index=documents([{'id':'apob','entity_type':'biomarker','name':'ApoB','aliases':['apolipoprotein B'],'summary':'Atherogenic particles','outcomes':[{'name':'Cardiovascular events'}],'studies':studies},
                              {'id':'psa','entity_type':'biomarker','name':'PSA','aliases':[],'outcomes':[],'studies':[{'pmid':'18','title':'PSA cohort','abstract':'PSA.','design':'Prospective cohort','population':'Human'}]}])

    def test_counts_every_linked_record_by_layer(self):
        result=match('ApoB and cardiovascular events in adults',self.index,study_limit=1)
        coverage=result['layer_coverage']['entities']['entity:apob'];cells=coverage['cells']
        self.assertEqual(len(result['studies']),1)  # coverage is not limited to retrieved records
        self.assertEqual({k:v['count'] for k,v in cells.items()},{'mechanism':0,'preclinical':1,'observational':1,'interventional':2,'guidelines':1})
        self.assertEqual(coverage['syntheses'],1);self.assertEqual(coverage['excluded'],1)
        self.assertEqual(cells['interventional']['reviewed'],1)
        self.assertEqual(cells['observational']['directions'],{'below':0,'above':1,'includes':0})
        self.assertEqual(cells['interventional']['directions'],{'below':1,'above':0,'includes':1})
        ids={s['id'] for s in self.index[1]}
        for cell in cells.values():
            self.assertTrue(all(example['id'] in ids for example in cell['examples']))
        self.assertNotIn('entity:psa',result['layer_coverage']['entities'])

    def test_interval_side_needs_a_no_difference_value(self):
        from evidence.matcher import interval_side
        self.assertEqual(interval_side({'measure':'C-index change','lower':0.0,'upper':0.0008}),'includes')
        self.assertIsNone(interval_side({'measure':'Sensitivity','lower':0.4,'upper':0.6}))
        self.assertIsNone(interval_side({'measure':'hazard ratio','lower':None,'upper':1.2}))
