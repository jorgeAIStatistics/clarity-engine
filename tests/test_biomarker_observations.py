import hashlib,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from evidence_pipeline.common import PipelineError
from evidence_pipeline.schemas.pico import SourceDocument
from evidence_pipeline.state import State
from evidence_pipeline.extraction.core import source_tokens
from evidence_pipeline.extraction.observations import decode_observations,ObservationProvider,ObservationExtractor,redecode
from evidence_pipeline.extraction.providers import ProviderOutput
from evidence.intent_graph.findings import statements,matcher_document,apply_observations,observation_layer,synthesize,linked_entities

REGISTRY=json.loads((Path(__file__).resolve().parents[1]/'evidence'/'intent_graph'/'registry.json').read_text())
NONE={'first_token':None,'last_token':None,'confidence':None}

def source(text,pmid='1'):
    return SourceDocument(id='pmid:'+pmid,kind='abstract',pmid=pmid,pmcid=None,doi=None,source_url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',version='test',retrieved_at=datetime(2026,9,15,tzinfo=timezone.utc),text=text,sha256=hashlib.sha256(text.encode()).hexdigest())

class Tokens:
    def __init__(self,text):self.tokens=[t[2] for t in source_tokens(text)]
    def at(self,word,nth=0,length=1):
        hits=[i for i,t in enumerate(self.tokens) if t==word]
        return {'first_token':hits[nth],'last_token':hits[nth]+length-1,'confidence':0.9}

def observation(**fields):
    base={k:NONE for k in ('marker','target','population','setting','comparator','assay','measure_quote','value','unit','lower','upper','level','threshold','threshold_unit','n','p_value','statement')}
    base.update(p_operator='not_reported');base.update(fields);return base
def payload(*items,design='not_determined'):
    return {'study_design':design,'design_quote':NONE,'observations':list(items)}

CGA=("SYNTHETIC TEST ONLY. Chromogranin A in neuroendocrine neoplasms\n\n"
     "Serum chromogranin A (CgA) was measured in 120 patients with neuroendocrine neoplasms and 80 controls. "
     "At a cut-off of 100 ng/mL, CgA had a sensitivity of 71% and a specificity of 85% for neuroendocrine neoplasms. "
     "The area under the ROC curve was 0.82 (95% CI 0.76-0.88). "
     "Guidelines recommend CgA for monitoring rather than screening.")
C=Tokens(CGA);CGA_SOURCE=source(CGA)
SENSITIVITY=observation(observation_type='classification',measure='sensitivity',marker=C.at('CgA',1),target=C.at('neuroendocrine',2,2),measure_quote=C.at('sensitivity'),value=C.at('71'),unit=C.at('%'),threshold=C.at('100'),threshold_unit=C.at('ng',0,3),assay=C.at('Serum',0,3))
AUC=observation(observation_type='discrimination',measure='auc',marker=C.at('CgA',1),target=C.at('neuroendocrine',2,2),measure_quote=C.at('area',0,5),value=C.at('0.82'),lower=C.at('0.76'),upper=C.at('-0.88'),level=C.at('95'))

EGFR=("SYNTHETIC TEST ONLY. Adjuvant EGFR-TKI in resected NSCLC\n\n"
      "Pathological stage (IIIA vs IIIB; P=0.01) was associated with disease-free survival. "
      "EGFR mutation status was significantly associated with overall survival (P=0.03). "
      "Patients with EGFR mutations had longer progression-free survival (hazard ratio 0.62, 95% CI 0.48 to 0.80).")
E=Tokens(EGFR);EGFR_SOURCE=source(EGFR,'2')
STAGE=observation(observation_type='association',measure='p_value',marker=E.at('Pathological',0,2),target=E.at('disease-free',0,2),measure_quote=E.at('P',0,2),p_value=E.at('0.01'),p_operator='eq')
STATUS=observation(observation_type='association',measure='p_value',marker=E.at('EGFR',0,3),target=E.at('overall',0,2),measure_quote=E.at('P',1,2),p_value=E.at('0.03'),p_operator='eq')
HR=observation(observation_type='prognosis',measure='hazard_ratio',marker=E.at('EGFR',1,2),target=E.at('progression-free',0,2),measure_quote=E.at('hazard',0,2),value=E.at('0.62'),lower=E.at('0.48'),upper=E.at('0.80'),level=E.at('95'))

class FindingKindTests(unittest.TestCase):
    def test_classification_needs_no_ratio_interval_comparator_or_design(self):
        decoded=decode_observations(payload(SENSITIVITY),CGA_SOURCE)
        f=decoded['findings'][0]
        self.assertEqual((f['kind'],f['measure'],f['value'],f['threshold'],f['threshold_unit'],f['assay'],f['lower'],f['comparator']),('classification','sensitivity',71.0,100.0,'ng/mL','Serum chromogranin A',None,None))
        self.assertEqual(decoded['design']['study_design'],'not_determined')
        self.assertEqual(CGA[f['passage']['start']:f['passage']['end']],f['passage']['text'])

    def test_range_hyphen_is_not_a_negative_bound(self):
        auc=decode_observations(payload(AUC),CGA_SOURCE)['findings'][0]
        self.assertEqual((auc['kind'],auc['value'],auc['lower'],auc['upper'],auc['level']),('discrimination',0.82,0.76,0.88,95.0))

    def test_egfr_survival_associations_are_prognosis_and_keep_intervals(self):
        decoded=decode_observations(payload(STAGE,STATUS,HR),EGFR_SOURCE)
        self.assertEqual([f['kind'] for f in decoded['findings']],['prognosis','prognosis','prognosis'])
        self.assertEqual([a.get('normalized') for a in decoded['audit']],['association_to_prognosis','association_to_prognosis'])
        hr=decoded['findings'][2]
        self.assertEqual((hr['value'],hr['lower'],hr['upper']),(0.62,0.48,0.80))

    def test_effect_requires_an_interval_and_rejections_are_typed(self):
        effect_without_interval=dict(HR,observation_type='effect',lower=NONE,upper=NONE)
        wrong_kind=dict(SENSITIVITY,measure='hazard_ratio')
        guideline_on_wrong_sentence=observation(observation_type='guideline',measure='recommendation',marker=C.at('CgA',1),statement=C.at('sensitivity',0,3))
        decoded=decode_observations(payload(effect_without_interval),EGFR_SOURCE)
        self.assertEqual(decoded['dead_letters'],{'rejected_missing_fields':1})
        decoded=decode_observations(payload(wrong_kind,guideline_on_wrong_sentence,dict(SENSITIVITY,target=NONE)),CGA_SOURCE)
        self.assertEqual([a['dead_letter'] for a in decoded['audit']],['rejected_wrong_kind','rejected_unsupported_passage','rejected_missing_fields'])
        self.assertEqual(decode_observations(payload(),CGA_SOURCE)['dead_letters'],{'no_observations_reported':1})
        guideline=observation(observation_type='guideline',measure='recommendation',marker=C.at('CgA',2),statement=C.at('Guidelines',0,8))
        self.assertEqual(decode_observations(payload(guideline),CGA_SOURCE)['findings'][0]['kind'],'guideline')

    def test_design_claim_without_its_phrase_is_not_kept(self):
        decoded=decode_observations(payload(SENSITIVITY,design='diagnostic_accuracy'),CGA_SOURCE)
        self.assertEqual((decoded['design']['study_design'],decoded['audit'][0]['reason']),('not_determined','design_without_evidence'))

    def test_saved_v1_output_without_new_fields_replays_without_a_call(self):
        legacy={**payload(SENSITIVITY),'observations':[{k:v for k,v in SENSITIVITY.items() if k not in ('setting','assay')}]}
        record=redecode({'id':'attempt-1','raw_payload':legacy},CGA_SOURCE.model_dump(mode='json'))
        self.assertEqual((record['findings'][0]['kind'],record['findings'][0]['assay'],record['redecoded_from']),('classification',None,'attempt-1'))

class ExtractorTests(unittest.TestCase):
    def test_extractor_budgets_caches_and_remembers_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(os.path.join(folder,'state.sqlite3'))
            provider=ObservationProvider('anthropic','test-model','test-key')
            with patch.object(ObservationProvider,'extract',return_value=ProviderOutput(payload(SENSITIVITY),'msg_1',10,10,raw_payload=payload(SENSITIVITY))) as call:
                key,record=ObservationExtractor(provider,state,daily_calls=5).extract(CGA_SOURCE,run_id='test')
                again,_=ObservationExtractor(provider,state,daily_calls=5).extract(CGA_SOURCE,run_id='test')
            self.assertEqual((key,call.call_count),(again,1))
            [attempt]=state.all('observation_attempt')
            self.assertEqual((attempt['status'],attempt['pmid']),('validated','1'))
            provider.close();state.close()

    def test_failed_extraction_keeps_typed_dead_letters(self):
        with tempfile.TemporaryDirectory() as folder:
            state=State(os.path.join(folder,'state.sqlite3'))
            provider=ObservationProvider('anthropic','test-model','test-key')
            bad=payload(dict(SENSITIVITY,value=NONE))
            with patch.object(ObservationProvider,'extract',return_value=ProviderOutput(bad,'msg_2',10,10,raw_payload=bad)):
                with self.assertRaises(PipelineError):ObservationExtractor(provider,state,daily_calls=5).extract(CGA_SOURCE,run_id='test')
            [attempt]=state.all('observation_attempt')
            self.assertEqual((attempt['code'],attempt['dead_letters']),('no_supported_observations',{'rejected_missing_fields':1}))
            provider.close();state.close()

class GraphLinkingTests(unittest.TestCase):
    def record(self,*items,text_source=CGA_SOURCE):
        return dict(decode_observations(payload(*items),text_source),study_id=text_source.id,source=text_source.model_dump(mode='json'),extracted_at='2026-09-15T00:00:00+00:00',version='biomarker-observations-v2')

    def test_findings_link_only_the_marker_named_in_their_own_span(self):
        record=self.record(STAGE,STATUS,HR,text_source=EGFR_SOURCE)
        by_marker={f['marker']:[n['id'] for n in linked_entities(f,REGISTRY)] for f in record['findings']}
        self.assertEqual(by_marker,{'Pathological stage':[],'EGFR mutation status':['variant:egfr-activating-mutation'],'EGFR mutations':['variant:egfr-activating-mutation']})
        cypher,linked=statements(record,REGISTRY)
        self.assertEqual(linked,['variant:egfr-activating-mutation'])
        text=json.dumps([p for _,p in cypher])
        for other in ('biomarker:her2','gene:brca1','test:mammography','biomarker:egfr'):self.assertNotIn('"'+other+'"',text)
        self.assertTrue(any("CASE WHEN f.review_state='reviewed'" in q for q,_ in cypher))
        self.assertTrue(any('SUPPORTED_BY' in q for q,_ in cypher) and any('EVIDENCED_BY' in q for q,_ in cypher) and any('FOR_OUTCOME' in q for q,_ in cypher))

    def test_drug_classes_built_on_a_marker_name_do_not_link_it(self):
        ids=lambda marker:[n['id'] for n in linked_entities({'marker':marker},REGISTRY)]
        self.assertEqual(ids('generation of EGFR-TKI'),[])
        self.assertEqual(ids('anti-HER2 therapy'),[])
        self.assertEqual(ids('EGFR-mutant'),['variant:egfr-activating-mutation'])
        self.assertEqual(ids('HER2-positive status'),['biomarker:her2'])
        self.assertEqual(ids('synaptophysin and chromogranin A'),[])
        self.assertEqual(ids('synaptophysin, chromogranin A and INSM1'),[])
        self.assertEqual(ids('chromogranin A'),['biomarker:chromogranin-a'])

    def test_matcher_document_layers_and_sentences(self):
        record=self.record(SENSITIVITY,AUC)
        doc=matcher_document(record,REGISTRY)
        self.assertEqual((doc['layer'],doc['layer_basis'],doc['design']),('observational','finding_kind','Design not determined'))
        self.assertTrue(all(f['quote'] in doc['_text'] and f['plot_eligible'] is False and f['entity_ids']==['biomarker:chromogranin-a'] for f in doc['findings']))
        merged=apply_observations({'id':'pmid:1','layer':'unclassified','design':'','findings':[{'outcome':'kept'}]},record,REGISTRY)
        self.assertEqual((merged['layer'],len(merged['findings'])),('observational',3))
        self.assertEqual(observation_layer('not_determined',[dict(record['findings'][0],population='nude mice')]),'preclinical')
        self.assertTrue(synthesize('CA-125','guidelines',[])[0].startswith('No indexed guideline findings for CA-125 yet.'))
        self.assertIn('classification',synthesize('Chromogranin A','observational',[{'kind':'classification','measure':'sensitivity','estimate':71.0,'target':'neuroendocrine neoplasms','cutoff':100.0,'cutoff_unit':'ng/mL'}])[0])

    def test_registry_molecular_identity(self):
        by={n['id']:n for n in REGISTRY}
        self.assertEqual(by['variant:egfr-l858r']['variant_of'],'gene:egfr')
        self.assertEqual(by['biomarker:il-18']['encoded_by'],'gene:il18')
        self.assertEqual((by['gene:brca1']['type'],'biomarker:brca1' in by),('gene',False))
        self.assertNotIn('EGFR mutation',by['biomarker:egfr']['aliases'])
        self.assertGreaterEqual(sum(n['type']=='biomarker' for n in REGISTRY),100)
