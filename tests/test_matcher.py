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
