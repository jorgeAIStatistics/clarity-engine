import copy
import unittest
from evidence.visual_report import build_reports, release
from living_research.automatic import auto_publish, current_releases, extract_reported_study
from living_research.store import Store

class VisualReleaseTests(unittest.TestCase):
    def setUp(self):
        self.paper={'pmid':'12345678','title':'Randomized example trial','abstract':'Adults were randomized to creatine versus placebo. The endpoint was mortality (hazard ratio, 0.80; 95% CI, 0.60 to 0.95).','year':'2026'}
        self.target={'name':'creatine','aliases':[]}
        self.study=extract_reported_study(self.paper,self.target)
    def test_literal_release_without_human_gate(self):
        row,error=release(self.study,self.study['findings'][0])
        self.assertIsNone(error);self.assertEqual(row['point'],.8)
        self.assertEqual(row['assessment'],'Automated source validation')
    def test_invalid_values_and_source_are_blocked(self):
        for field,value in [('estimate',float('nan')),('estimate',True),('lower',.9),('upper',-.1),('confidence_level',90)]:
            finding=copy.deepcopy(self.study['findings'][0]);finding['effect'][field]=value
            self.assertIsNone(release(self.study,finding)[0])
        self.study['abstract']+=' changed'
        self.assertEqual(release(self.study,self.study['findings'][0])[1],'source_hash')
    def test_numbers_from_different_tuples_cannot_be_combined(self):
        self.paper['abstract']+=' Another endpoint was stroke (hazard ratio, 0.70; 95% CI, 0.50 to 0.90).'
        study=extract_reported_study(self.paper,self.target)
        finding=copy.deepcopy(study['findings'][0]);finding['effect']['lower']=.5
        finding['quote']=self.paper['abstract'];finding['source_span']={'text':finding['quote'],'start':0,'end':len(finding['quote']),'source_id':'pmid:12345678'}
        self.assertEqual(release(study,finding)[1],'interval_tuple')
    def test_automatic_release_is_idempotent_and_invalidates_changed_sources(self):
        store=Store(':memory:')
        proposal={'id':'p1','paper':self.paper,'target':self.target,'paper_id':'pmid:12345678','target_id':'compound:creatine','fingerprint':'f1','scope_hash':'s1'}
        store.put('paper',proposal['paper_id'],{'fingerprint':'f1'})
        store.put('target',proposal['target_id'],{'scope_hash':'s1'})
        self.assertTrue(auto_publish(store,proposal));self.assertFalse(auto_publish(store,proposal))
        self.assertEqual(len(current_releases(store,proposal['target_id'])),1)
        store.put('paper',proposal['paper_id'],{'fingerprint':'f2'})
        self.assertEqual(current_releases(store,proposal['target_id']),[])
        self.assertFalse(store.get('audit','visual:p1')['clinical_grade_changed']);store.close()
    def test_launch_density_and_no_invented_inference(self):
        profiles=build_reports()['profiles'];records={r['id']:r for p in profiles.values() for r in p['records']}
        self.assertGreaterEqual(sum(bool(p['records']) for p in profiles.values()),10)
        self.assertGreaterEqual(len(records),30)
        for row in records.values():
            self.assertEqual(row['origin'],'reported')
            self.assertNotIn('certainty',row)
            self.assertEqual(row['sourceText'][row['span']['start']:row['span']['end']],row['quote'])
    def test_correction_and_unrelated_source_rejected(self):
        self.paper['corrections']=['notice'];self.assertIsNone(extract_reported_study(self.paper,self.target))
        self.paper.pop('corrections');self.assertIsNone(extract_reported_study(self.paper,{'name':'unrelated'}))

if __name__=='__main__':unittest.main()
