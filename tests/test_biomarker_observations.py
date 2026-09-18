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

AUCONLY=("SYNTHETIC TEST ONLY. Model discrimination\n\n"
     "The model achieved an area under the ROC curve of 0.78 for recurrence.")
A=Tokens(AUCONLY);AUC_SOURCE=source(AUCONLY,'3')

GROUPED=("SYNTHETIC TEST ONLY. Median IL-18 in Still's disease\n\n"
     "Median baseline IL-18 levels were higher in active disease at 61,425 pg/mL (interquartile range 16,194-235,746) in 40 patients.")
G=Tokens(GROUPED);GROUPED_SOURCE=source(GROUPED,'4')

class GroupedNumberTests(unittest.TestCase):
    def observation_on(self, token_index):
        return observation(observation_type='association',measure='median',marker=G.at('IL',1,2),target=G.at('active',0,2),
                           measure_quote=G.at('Median',1),value=token_index,unit=G.at('pg',0,3))

    def test_a_span_on_either_half_reads_the_whole_grouped_number(self):
        first=decode_observations(payload(self.observation_on(G.at('61'))),GROUPED_SOURCE)
        self.assertEqual((first['findings'][0]['value'],first['findings'][0]['value_raw']),(61425.0,'61,425'))
        second=decode_observations(payload(self.observation_on(G.at('425'))),GROUPED_SOURCE)
        self.assertEqual(second['findings'][0]['value'],61425.0)

    def test_a_confidence_level_may_carry_its_percent_sign(self):
        """"(95% CI: 0.754-0.915)" spans two tokens, and refusing the sign threw the finding away.

        Four sound AUC and hazard-ratio rows from one CEA abstract were discarded this way, and the
        same happened wherever the model happened to span the level as "95 %" rather than "95".
        """
        text=("SYNTHETIC TEST ONLY. Combined model in resected disease\n\n"
              "A combined model achieved an AUC of 0.836 (95% CI: 0.754-0.915) in the validation cohort.")
        T=Tokens(text);src=source(text,'42726133')
        obs=observation(observation_type='discrimination',measure='auc',marker=T.at('model',1),target=T.at('validation',0,2),
                        measure_quote=T.at('AUC'),value=T.at('0.836'),lower=T.at('0.754'),upper=T.at('-0.915'),
                        level=T.at('95',0,2))
        decoded=decode_observations(payload(obs),src)
        self.assertEqual(decoded['dead_letters'],{},f"rejected: {decoded['excluded'] if 'excluded' in decoded else decoded['audit']}")
        self.assertEqual(len(decoded['findings']),1)
        found=decoded['findings'][0]
        self.assertEqual((found['value'],found['lower'],found['upper'],found['level']),(0.836,0.754,0.915,95.0))
        # Only the level is read this way. A VALUE keeps its unit in its own span, so a percent sign
        # inside a value span is still refused rather than silently becoming a bare number.
        from evidence_pipeline.extraction.observations import _number
        from evidence_pipeline.common import PipelineError
        self.assertEqual(_number({'raw':'95%'},'level'),95.0)
        self.assertEqual(_number({'raw':'95 %'},'level'),95.0)
        self.assertEqual(_number({'raw':'95'},'level'),95.0)
        with self.assertRaises(PipelineError):_number({'raw':'71%'},'value')

    def test_an_ordinary_number_and_a_range_are_untouched(self):
        plain=decode_observations(payload(dict(self.observation_on(G.at('40')),unit=NONE)),GROUPED_SOURCE)
        self.assertEqual(plain['findings'][0]['value'],40.0)
        auc=decode_observations(payload(AUC),CGA_SOURCE)['findings'][0]
        self.assertEqual((auc['value'],auc['lower'],auc['upper']),(0.82,0.76,0.88))

class SpanAndKindRecoveryTests(unittest.TestCase):
    def test_an_unusable_design_span_costs_the_design_not_the_findings(self):
        body=payload(SENSITIVITY,design='observational')
        body['design_quote']={'first_token':9999,'last_token':9999,'confidence':0.9}
        decoded=decode_observations(body,CGA_SOURCE)
        self.assertEqual([f['kind'] for f in decoded['findings']],['classification'])
        self.assertEqual(decoded['design']['study_design'],'not_determined')
        self.assertIn({'reason':'span_token_bounds_invalid','field':'design_quote'},decoded['audit'])
        self.assertEqual(decoded['dead_letters'],{})

    def test_an_auc_called_classification_becomes_discrimination_when_the_passage_supports_it(self):
        auc=observation(observation_type='classification',measure='auc',marker=A.at('model'),target=A.at('recurrence'),measure_quote=A.at('area',0,5),value=A.at('0.78'))
        decoded=decode_observations(payload(auc),AUC_SOURCE)
        self.assertEqual([f['kind'] for f in decoded['findings']],['discrimination'])
        self.assertEqual([a.get('normalized') for a in decoded['audit']],['classification_to_discrimination'])
        # A cut-off sentence stays classification; the normalization is not a catch-all.
        cutoff=observation(observation_type='classification',measure='sensitivity',marker=A.at('model'),target=A.at('recurrence'),measure_quote=A.at('area',0,5),value=A.at('0.78'))
        self.assertEqual(decode_observations(payload(cutoff),AUC_SOURCE)['dead_letters'],{'rejected_unsupported_passage':1})

    def test_a_reused_provider_never_reports_the_previous_sources_rejections(self):
        provider=ObservationProvider('anthropic','test-model','test-key')
        with self.assertRaises(PipelineError):
            provider.decode_payload(payload(dict(SENSITIVITY,value=NONE)),[CGA_SOURCE])
        self.assertEqual(provider.dead_letters,{'rejected_missing_fields':1})
        provider.decode_payload(payload(SENSITIVITY),[CGA_SOURCE])
        self.assertEqual((provider.dead_letters,provider.decode_audit),({},[]))
        provider.close()

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

    def test_a_marker_named_as_an_exclusion_criterion_is_not_the_marker(self):
        """A review reporting response rates in "patients without EGFR, ALK, or ROS1 alterations"
        put three risk ratios on the EGFR page, where they read as findings about measuring EGFR.
        They are the opposite: EGFR is who was kept OUT of the study."""
        ids=lambda marker,population:[n['id'] for n in linked_entities({'marker':marker,'population':population},REGISTRY)]
        excluded='patients without epidermal growth factor receptor (EGFR), anaplastic lymphoma kinase (ALK), or ROS proto-oncogene 1 (ROS1) alterations'
        self.assertEqual(ids('EGFR',excluded),[])
        self.assertEqual(ids('EGFR','EGFR-negative patients'),[])
        # A population the marker actually describes still links, and so does one that never mentions it.
        self.assertEqual(ids('EGFR','EGFR-positive patients'),['biomarker:egfr'])
        self.assertEqual(ids('EGFR','patients with advanced NSCLC'),['biomarker:egfr'])
        # The negation reaches to the end of its clause and no further.
        self.assertEqual(ids('EGFR','no prior therapy. EGFR-mutant patients'),['biomarker:egfr'])
        # Excluding one marker says nothing about a different one named in the span.
        self.assertEqual(ids('EGFR mutation','patients without ALK alterations'),['variant:egfr-activating-mutation'])

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
        # Large values are grouped and units spaced: "median 61,425 pg/mL", never "61425pg/mL".
        self.assertIn('median 61,425 pg/mL',synthesize('IL-18','observational',[{'kind':'association','measure':'median','estimate':61425.0,'unit':'pg/mL','target':'active disease'}])[0])
        self.assertIn('sensitivity 71% at a cut-off of 45,000 pg/mL',synthesize('IL-18','observational',[{'kind':'classification','measure':'sensitivity','estimate':71.0,'unit':'%','cutoff':45000.0,'cutoff_unit':'pg/mL','target':'x'}])[0])

    def test_a_paper_that_measured_something_else_is_named_as_such(self):
        from evidence.intent_graph.findings import unlinked_target
        record={'findings':[{'marker':'11C-PiB'},{'marker':'18F-flutemetamol'},{'marker':'11C-PiB'}]}
        self.assertEqual(unlinked_target(record,[],'test:amyloid-pet'),['11C-PiB','18F-flutemetamol'])
        self.assertIsNone(unlinked_target(record,['test:amyloid-pet'],'test:amyloid-pet'))
        self.assertEqual(unlinked_target({'findings':[]},[],'test:amyloid-pet'),[])

    def test_a_marker_and_treatment_pair_is_described_to_a_person(self):
        """Q1 leads with the identity sentence, and the Class row must not be the schema formula.

        RET x selpercatinib read "Variant x drug x condition" while every other pair read
        "Marker-and-treatment pair": a reader met the data model instead of the biology.
        """
        pairs=[n for n in REGISTRY if n['type']=='precision_context' and n['id']!='precision_context:radiotherapy']
        self.assertGreaterEqual(len(pairs),10)
        for node in pairs:
            with self.subTest(node['id']):
                self.assertTrue(node.get('identity_sentence'),'a pair with no sentence falls back to its class')
                self.assertEqual(node.get('entity_class'),'Marker-and-treatment pair')
                self.assertNotIn('\u00d7',node.get('entity_class',''),'a class is not a schema formula')
        ret=next(n for n in pairs if n['id']=='precision_context:ret-selpercatinib')
        self.assertIn('selpercatinib',ret['identity_sentence'])
        self.assertIn('RET fusion',ret['identity_sentence'])

    def test_registry_molecular_identity(self):
        by={n['id']:n for n in REGISTRY}
        self.assertEqual(by['variant:egfr-l858r']['variant_of'],'gene:egfr')
        self.assertEqual(by['biomarker:il-18']['encoded_by'],'gene:il18')
        self.assertEqual((by['gene:brca1']['type'],'biomarker:brca1' in by),('gene',False))
        self.assertNotIn('EGFR mutation',by['biomarker:egfr']['aliases'])
        self.assertGreaterEqual(sum(n['type']=='biomarker' for n in REGISTRY),100)
