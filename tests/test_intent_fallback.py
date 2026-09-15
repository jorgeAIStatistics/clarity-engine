import os,unittest
from unittest.mock import patch
from evidence.matcher import documents
from evidence.service import CATALOG
from evidence.intent_graph.service import run

IL18='Interleukin-18 as a Potential Biomarker for Radiotherapy-Related Pain in Breast Cancer: Implications for Personalized Pain Management'
BANNED=('brca','her2','mammography','olaparib','trastuzumab','population to specify','outcome to specify','concepts you named')

class RuleFallbackTests(unittest.TestCase):
    """Without a Claude key or Neo4j, the map keeps the question's own entities."""
    def setUp(self):
        self.env=patch.dict(os.environ,{},clear=False);self.env.start();os.environ.pop('ANTHROPIC_API_KEY',None)
        self.index=patch('evidence.matcher.library_index',return_value=documents(CATALOG['entities']));self.index.start()
    def tearDown(self):self.index.stop();self.env.stop()
    def visible(self,result):
        q=result['copilot']['question']
        return ' '.join([q['restatement'],*(e['name'] for e in result['entities']),*(t['title']+' '+t['text'] for t in result['copilot']['tensions'])]).lower()

    def test_il18_title_is_il18_breast_cancer_radiotherapy_pain(self):
        result=run(IL18)
        self.assertEqual(result['parse'],{'mode':'rules','graph':'retained_library','reason':'intent_provider_not_configured'})
        self.assertEqual(result['copilot']['question']['restatement'],'IL-18 × breast cancer × radiotherapy-related pain. Population not specified.')
        self.assertEqual({e['id'] for e in result['entities']},{'biomarker:il-18','condition:breast-cancer','precision_context:radiotherapy'})
        text=self.visible(result)
        for word in ('il-18','breast cancer','radiotherapy-related pain','population not specified'):self.assertIn(word,text)
        for word in BANNED:self.assertNotIn(word,text)
        self.assertTrue({'association','clinical_utility'}<=set(result['intent']['intents']))
        self.assertIn('biomarker:il-18',result['layer_coverage']['entities'])

    def test_nfl_als_resolves(self):
        result=run('plasma NfL / ALS progression / trial enrichment')
        self.assertEqual({e['id'] for e in result['entities']},{'biomarker:nfl','condition:als'})
        self.assertTrue({'prediction','enrichment'}<=set(result['intent']['intents']))
        self.assertEqual(result['copilot']['question']['restatement'],'NfL × ALS × ALS progression / trial enrichment. Population not specified.')

    def test_apob_demo_resolves_named_markers_only(self):
        result=run('Does ApoB add information beyond LDL-C for predicting cardiovascular events in adults without cardiovascular disease, and is there evidence that acting on ApoB improves outcomes (clinical utility)? What do guidelines say?')
        self.assertEqual({e['id'] for e in result['entities']},{'biomarker:apob','biomarker:ldl-c'})
        self.assertEqual(result['copilot']['question']['restatement'],'ApoB × LDL-C × cardiovascular events. Population: adults without cardiovascular disease.')
        self.assertTrue(result['studies'])

    def test_unknown_marker_becomes_temporary_row(self):
        result=run('Galectin-3 as a potential biomarker for cardiotoxicity in breast cancer')
        temporary=[e for e in result['entities'] if e['id'].startswith('temporary:')]
        self.assertEqual([e['name'] for e in temporary],['Galectin-3'])
        self.assertTrue(temporary[0]['ephemeral'])
        self.assertIn(temporary[0]['id'],result['layer_coverage']['entities'])

    def test_personal_health_text_still_refused(self):
        with self.assertRaises(ValueError):run('Here are my blood test results: IL-18 is 400 pg/mL')

    def test_route_serves_rule_map_without_provider(self):
        from app import app
        response=app.test_client().post('/api/evidence/match',json={'text':IL18,'workspace':True})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['parse']['mode'],'rules')
