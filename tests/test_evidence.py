import json
import math
from pathlib import Path
import unittest
from flask import Flask
from evidence.routes import blueprint
from evidence.service import CATALOG, validate_catalog, diagnostic_metrics, screening_metrics, list_entities, assessment_framework

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__);app.register_blueprint(blueprint);self.client=app.test_client()
    def test_low_prevalence(self):
        m=diagnostic_metrics(.9,.95,.01)
        self.assertAlmostEqual(m['true_positive'],9)
        self.assertAlmostEqual(m['false_positive'],49.5)
        self.assertAlmostEqual(m['ppv'],9/58.5)
        self.assertAlmostEqual(m['npv'],940.5/941.5)
        self.assertAlmostEqual(m['lr_positive'],18)
    def test_boundaries(self):
        self.assertIsNone(diagnostic_metrics(1,1,0)['ppv'])
        self.assertIsNone(diagnostic_metrics(1,1,1)['npv'])
        self.assertEqual(diagnostic_metrics(1,1,.5)['ppv'],1)
        self.assertIsNone(diagnostic_metrics(1,1,.5)['diagnostic_odds_ratio'])
        self.assertEqual(diagnostic_metrics(0,0,.5)['ppv'],0)
    def test_counts_conserved(self):
        for se in (0,.2,.9,1):
            for sp in (0,.7,1):
                for p in (0,.01,.5,1):
                    m=diagnostic_metrics(se,sp,p)
                    self.assertAlmostEqual(sum(m[k] for k in ['true_positive','true_negative','false_positive','false_negative']),1000)
    def test_invalid_probabilities(self):
        for value in (True,None,'90',-1,1.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):diagnostic_metrics(value,.95,.01)
    def test_screening_benefit_and_harm(self):
        self.assertEqual(screening_metrics(.01,.008)['number_needed_to_screen'],500)
        self.assertEqual(screening_metrics(.03,.01)['number_needed_to_screen'],50)
        self.assertIsNone(screening_metrics(5e-324,0)['number_needed_to_screen'])
        self.assertIsNone(screening_metrics(.01,.01)['number_needed_to_screen'])
        self.assertEqual(screening_metrics(.008,.01)['number_needed_to_harm'],500)
    def test_catalog(self):
        self.assertTrue(validate_catalog(CATALOG))
        self.assertEqual(len(list_entities('biomarker')),12)
        self.assertIn('egfr-osimertinib',[e['id'] for e in list_entities(query='EGFR')])
        self.assertNotIn('Efficacy',assessment_framework('biomarker')['dimensions'])
        exported=Path(__file__).resolve().parents[2]/'clarity-web/src/evidence/catalog.json'
        if exported.exists(): self.assertEqual(CATALOG,json.loads(exported.read_text()))
    def test_api_catalog(self):
        self.assertEqual(self.client.get('/api/entities?entity_type=biomarker').status_code,200)
        self.assertEqual(self.client.get('/api/entities?entity_type=wrong').status_code,400)
        self.assertEqual(self.client.get('/api/entities/missing').status_code,404)
        self.assertEqual(self.client.get('/api/entities/apob').json['entity_type'],'biomarker')
        self.assertEqual(len(self.client.get('/api/evidence/frameworks').json['frameworks']),5)
    def test_api_calculator(self):
        response=self.client.post('/api/statistics/diagnostic',json={'sensitivity':.9,'specificity':.95,'prevalence':.01})
        self.assertEqual(response.status_code,200)
        self.assertAlmostEqual(response.json['ppv'],9/58.5)
        for body in ([],None,{}, {'sensitivity':True,'specificity':.9,'prevalence':.1}, {'sensitivity':.9,'specificity':.9,'prevalence':.1,'unknown':2}):
            self.assertEqual(self.client.post('/api/statistics/diagnostic',json=body).status_code,400)
        self.assertEqual(self.client.post('/api/statistics/screening',json={'baseline_risk':.01,'screened_risk':.008}).json['number_needed_to_screen'],500)

if __name__=='__main__':unittest.main()

class AppraisalTests(unittest.TestCase):
    def test_domains_do_not_reuse_compound_grades(self):
        from evidence.appraisal import grade_entity
        for entity in CATALOG['entities']:
            result=grade_entity(entity)
            self.assertIsNone(result['overall_grade'])
            self.assertTrue(all(a['rating']=='Not yet assessed' for a in result['assessments'].values()))
    def test_review_requires_real_provenance(self):
        from evidence.appraisal import grade_entity
        entity=CATALOG['entities'][0]
        with self.assertRaises(ValueError):grade_entity(entity,{'Analytical validity':{'rating':'Strong'}})
        with self.assertRaises(ValueError):grade_entity(entity,{'Efficacy':{'rating':'Strong'}})
        review={'rating':'Moderate','reviewer':'Test fixture reviewer','reviewed_at':'2026-09-13','rationale':'Test fixture, not a clinical appraisal','source_ids':[entity['sources'][0]['url']],'population':'Fixture population','outcome':'Fixture outcome','limitations':'Fixture only'}
        result=grade_entity(entity,{'Analytical validity':review})
        self.assertEqual(result['assessments']['Analytical validity']['rating'],'Moderate')
        self.assertEqual(result['assessments']['Clinical utility']['rating'],'Not yet assessed')
