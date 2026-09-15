import hashlib,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from evidence_pipeline.common import PipelineError
from evidence_pipeline.schemas.pico import SourceDocument
from evidence_pipeline.state import State
from evidence_pipeline.extraction.core import source_tokens
from evidence_pipeline.extraction.observations import decode_observations,ObservationProvider,ObservationExtractor
from evidence_pipeline.extraction.providers import ProviderOutput
from evidence.intent_graph.findings import statements,matcher_document,apply_observations,observation_layer

TEXT=("SYNTHETIC TEST ONLY. Chromogranin A in neuroendocrine neoplasms\n\n"
      "Serum chromogranin A (CgA) was measured in 120 patients with neuroendocrine neoplasms and 80 controls. "
      "At a cut-off of 100 ng/mL, CgA had a sensitivity of 71% and a specificity of 85% for neuroendocrine neoplasms. "
      "The area under the ROC curve was 0.82 (95% CI 0.76-0.88). "
      "Higher CgA was associated with shorter overall survival (hazard ratio 2.1, 95% CI 1.3 to 3.4). "
      "Guidelines recommend CgA for monitoring rather than screening.")
SOURCE=SourceDocument(id='pmid:1',kind='abstract',pmid='1',pmcid=None,doi=None,source_url='https://pubmed.ncbi.nlm.nih.gov/1/',version='test',retrieved_at=datetime(2026,9,15,tzinfo=timezone.utc),text=TEXT,sha256=hashlib.sha256(TEXT.encode()).hexdigest())
TOKENS=[t[2] for t in source_tokens(TEXT)]
REGISTRY=json.loads((Path(__file__).resolve().parents[1]/'evidence'/'intent_graph'/'registry.json').read_text())

def at(word,nth=0,length=1):
    hits=[i for i,t in enumerate(TOKENS) if t==word]
    return {'first_token':hits[nth],'last_token':hits[nth]+length-1,'confidence':0.9}
NONE={'first_token':None,'last_token':None,'confidence':None}
def observation(**fields):
    base={k:NONE for k in ('marker','target','population','comparator','measure_quote','value','unit','lower','upper','level','threshold','threshold_unit','n','p_value','statement')}
    base.update(p_operator='not_reported');base.update(fields);return base
def payload(*items,design='not_determined'):
    return {'study_design':design,'design_quote':NONE,'observations':list(items)}
SENSITIVITY=observation(observation_type='classification',measure='sensitivity',marker=at('CgA',1),target=at('neuroendocrine',1,2),measure_quote=at('sensitivity'),value=at('71'),unit=at('%'),threshold=at('100'),threshold_unit=at('ng',0,3))
AUC=observation(observation_type='discrimination',measure='auc',marker=at('CgA',1),target=at('neuroendocrine',1,2),measure_quote=at('area',0,5),value=at('0.82'),lower=at('0.76'),upper=at('-0.88'),level=at('95'))
HR=observation(observation_type='prognosis',measure='hazard_ratio',marker=at('CgA',2),target=at('overall',0,2),measure_quote=at('hazard',0,2),value=at('2.1'),lower=at('1.3'),upper=at('3.4'),level=at('95',1))

class ObservationDecodeTests(unittest.TestCase):
    def test_classification_needs_no_ratio_interval_or_design(self):
        decoded=decode_observations(payload(SENSITIVITY),SOURCE)
        f=decoded['findings'][0]
        self.assertEqual((f['observation_type'],f['measure'],f['value'],f['threshold'],f['threshold_unit'],f['lower']),('classification','sensitivity',71.0,100.0,'ng/mL',None))
        self.assertEqual(decoded['design']['study_design'],'not_determined')
        self.assertEqual(TEXT[f['passage']['start']:f['passage']['end']],f['passage']['text'])
        self.assertIn('sensitivity of 71%',f['passage']['text'])

    def test_range_hyphen_is_not_a_negative_bound_and_prognosis_keeps_its_interval(self):
        decoded=decode_observations(payload(AUC,HR),SOURCE)
        auc,hr=decoded['findings']
        self.assertEqual((auc['value'],auc['lower'],auc['upper'],auc['level']),(0.82,0.76,0.88,95.0))
        self.assertEqual((hr['observation_type'],hr['value'],hr['lower'],hr['upper']),('prognosis',2.1,1.3,3.4))

    def test_passage_must_support_the_type_and_measure(self):
        wrong_type=observation(observation_type='guideline',measure='recommendation',marker=at('CgA',1),statement=at('sensitivity',0,3))
        wrong_measure=dict(SENSITIVITY,observation_type='classification',measure='hazard_ratio')
        out_of_range=dict(SENSITIVITY,unit=NONE,value=at('71'))
        missing_target=dict(SENSITIVITY,target=NONE)
        decoded=decode_observations(payload(wrong_type,wrong_measure,missing_target),SOURCE)
        self.assertEqual([a['reason'] for a in decoded['audit']],['measure_not_supported_by_passage','measure_not_valid_for_type','observation_required_field_missing'])
        self.assertEqual(decode_observations(payload(out_of_range),SOURCE)['findings'][0]['value'],71.0)  # the % sign after 71 marks percent scale
        guideline=observation(observation_type='guideline',measure='recommendation',marker=at('CgA',3),statement=at('Guidelines',0,8))
        self.assertEqual(decode_observations(payload(guideline),SOURCE)['findings'][0]['observation_type'],'guideline')

    def test_design_claim_without_its_phrase_is_not_kept(self):
        decoded=decode_observations(payload(SENSITIVITY,design='diagnostic_accuracy'),SOURCE)
        self.assertEqual(decoded['design']['study_design'],'not_determined')
        self.assertEqual(decoded['audit'][0]['reason'],'design_without_evidence')

    def test_provider_rejects_when_nothing_is_supported(self):
        provider=ObservationProvider('anthropic','test-model','test-key')
        with self.assertRaises(PipelineError) as error:provider.decode_payload(payload(dict(SENSITIVITY,target=NONE)),[SOURCE])
        self.assertEqual(str(error.exception),'no_supported_observations')
        provider.close()

class ExtractorAndGraphTests(unittest.TestCase):
    def test_extractor_budgets_caches_and_records_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(os.path.join(folder,'state.sqlite3'))
            provider=ObservationProvider('anthropic','test-model','test-key')
            with patch.object(ObservationProvider,'extract',return_value=ProviderOutput(payload(SENSITIVITY),'msg_1',10,10,raw_payload=payload(SENSITIVITY))) as call:
                key,record=ObservationExtractor(provider,state,daily_calls=5).extract(SOURCE,run_id='test')
                again,_=ObservationExtractor(provider,state,daily_calls=5).extract(SOURCE,run_id='test')
            self.assertEqual((key,call.call_count),(again,1))
            self.assertEqual(record['findings'][0]['observation_type'],'classification')
            self.assertEqual([a['status'] for a in state.all('observation_attempt')],['validated'])
            provider.close();state.close()

    def test_graph_links_only_the_named_marker_and_uses_observation_layer(self):
        record=dict(decode_observations(payload(SENSITIVITY,HR),SOURCE),study_id='pmid:1',source=SOURCE.model_dump(mode='json'),extracted_at='2026-09-15T00:00:00+00:00',version='biomarker-observations-v1')
        cypher,linked=statements(record,REGISTRY)
        self.assertEqual(linked,['biomarker:chromogranin-a'])
        text=json.dumps([p for _,p in cypher])
        for other in ('biomarker:her2','biomarker:brca1','test:mammography'):self.assertNotIn(other,text)
        doc=matcher_document(record)
        self.assertEqual((doc['layer'],doc['layer_basis'],doc['design']),('observational','observation_type','Design not determined'))
        self.assertTrue(all(f['quote'] in doc['_text'] and f['plot_eligible'] is False for f in doc['findings']))
        merged=apply_observations({'id':'pmid:1','layer':'unclassified','design':'','findings':[{'outcome':'kept'}]},record)
        self.assertEqual((merged['layer'],len(merged['findings'])),('observational',3))
        self.assertEqual(observation_layer('not_determined',[dict(record['findings'][0],population='nude mice')]),'preclinical')

    def test_registry_aliases_for_egfr_and_chromogranin_a(self):
        names={n['name']:n['aliases'] for n in REGISTRY}
        self.assertTrue({'ERBB1','HER1'}<=set(names['EGFR']))
        self.assertIn('chromogranin-A',names['Chromogranin A'])

    def test_graph_stats_route(self):
        from app import app
        client=app.test_client()
        with patch('evidence.intent_graph.store.graph_stats',return_value={'version':'graph-stats-v1','findings':2}):
            response=client.get('/api/evidence/graph/stats?entity=biomarker:egfr')
        self.assertEqual((response.status_code,response.json['findings']),(200,2))
        with patch('evidence.intent_graph.store.graph_stats',side_effect=RuntimeError('neo4j_configuration_missing')):
            self.assertEqual(client.get('/api/evidence/graph/stats').status_code,503)
