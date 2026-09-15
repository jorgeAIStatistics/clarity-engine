import json,unittest
from pathlib import Path
from evidence.intent_graph.intent import ResearchIntent,EntityIntent,resolve_alias,complete_entities
from evidence.intent_graph.service import constrained
ROOT=Path(__file__).resolve().parents[1]/'evidence'/'intent_graph'
class IntentGraphTests(unittest.TestCase):
    def setUp(self):self.nodes=json.loads((ROOT/'registry.json').read_text())
    def test_explicit_alias_gold_set(self):
        for case in json.loads((ROOT/'gold.json').read_text()):
            intent=ResearchIntent.model_construct(entities=[],outcomes=[],population=None,setting_exposure=[],intents=[],explicitly_not_in_question=[])
            intent=complete_entities(intent,case['question'],self.nodes)
            matched={n['id'] for e in intent.entities if (n:=resolve_alias(e,self.nodes))}
            self.assertFalse(matched&set(case['forbidden']),case['question'])
            self.assertTrue(set(case['expected'])<=matched,(case['question'],matched))
    def test_no_sibling_study_or_leftover_tension(self):
        node=next(n for n in self.nodes if n['name']=='IL-18')
        intent=ResearchIntent(entities=[EntityIntent(name='IL-18',type='biomarker',synonyms=[],question_span='IL-18')],outcomes=['pain'],population=None,setting_exposure=['radiotherapy'],intents=['association','clinical_utility'],explicitly_not_in_question=['HER2'])
        foreign=dict(id='pmid:1',entity_ids=[node['id']],title='IL-18 radiotherapy breast cancer survival',_text='IL-18 measured during radiotherapy but no relevant endpoint.',findings=[])
        result=constrained('IL-18 and radiotherapy-related pain',intent,[node],[foreign])
        self.assertEqual(len(result['entities']),1)
        self.assertEqual(result['studies'],[])
        self.assertIn('IL-18',result['copilot']['question']['restatement'])
        self.assertNotIn('HER2',result['copilot']['question']['restatement'])
        self.assertTrue(all(c['count']==0 for c in result['layer_coverage']['entities'][node['id']]['cells'].values()))
    def test_ambiguous_marker_symbol_not_guessed(self):
        e=EntityIntent(name='EGFR',type='biomarker',synonyms=[],question_span='eGFR')
        self.assertEqual(resolve_alias(e,self.nodes)['id'],'biomarker:renal-egfr')
    def test_registry_has_100_unique_biomarkers_with_aliases(self):
        markers=[n for n in self.nodes if n['type']=='biomarker']
        self.assertGreaterEqual(len(markers),100)
        self.assertEqual(len({n['id'] for n in markers}),len(markers))
        self.assertTrue(all(n['name'] in n['aliases'] for n in markers))
