import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from living_research.store import Store
from living_research.providers import PubMed, identities, IncompleteSearch
from living_research.engine import Monitor, discover_targets, deduplicate, retrieve_window
from living_research.extraction import validate_extraction, Extractor as AIExtractor
from living_research.workflow import review, publish, rebase

PAPER={'source':'pubmed','source_id':'123','pmid':'123','doi':'10.1/abc','title':'ApoB in adults','abstract':'In 100 adults, ApoB was measured. No treatment effect was tested.','url':'https://pubmed.ncbi.nlm.nih.gov/123/','publication_types':['Observational Study']}
TARGET={'id':'entity:apob','name':'ApoB','entity_type':'biomarker','aliases':['apolipoprotein B']}
class Provider:
    name='pubmed'
    def __init__(self,fail=False,records=None):self.fail=fail;self.records=records if records is not None else [PAPER]
    def search(self,target,since,until,limit):
        if self.fail:raise RuntimeError('offline')
        return self.records,{'complete':True,'query':'ApoB','since':since,'until':until,'count':len(self.records)}
class Extractor:
    calls=0;max_calls=20
    def extract(self,target,paper):
        self.calls+=1
        return {'status':'review_ready','facts':validate_extraction({'population':{'value':'100 adults','quote':'In 100 adults, ApoB was measured.'}},paper)}
class LivingResearchTests(unittest.TestCase):
    def setUp(self):self.store=Store(':memory:')
    def tearDown(self):self.store.close()
    def monitor(self,provider=None):return Monitor(self.store,providers={'pubmed':provider or Provider()},extractor=Extractor())
    def test_all_new_domains_discovered(self):
        targets=discover_targets(False)
        self.assertEqual(len(targets),18)
        self.assertEqual({t['entity_type'] for t in targets},{'biomarker','diagnostic','screening','precision_oncology'})
    def test_bridge_deduplication(self):
        groups=deduplicate([{'source':'pubmed','pmid':'123'},{'source':'europe_pmc','doi':'https://doi.org/10.1/ABC'},{'source':'pubmed','pmid':'123','doi':'10.1/abc'}])
        self.assertEqual(len(groups),1)
        self.assertIn('doi:10.1/abc',groups[0]['ids'])
    def test_quote_and_numeric_validation(self):
        self.assertRaises(ValueError,validate_extraction,{'population':{'value':'10 adults','quote':'In 100 adults, ApoB was measured.'}},PAPER)
        self.assertRaises(ValueError,validate_extraction,{'effect_sizes':{'value':'20% benefit','quote':'No treatment effect was tested.'}},PAPER)
        self.assertRaises(ValueError,validate_extraction,{'population':{'value':'100 adults','quote':'Invented source passage'}},PAPER)
        self.assertRaises(ValueError,validate_extraction,{'grade':'Strong'},PAPER)
    def test_ai_budget_and_domain_context(self):
        calls=[]
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text=json.dumps({'population':{'value':'100 adults','quote':'In 100 adults, ApoB was measured.'}}))])
        extractor=AIExtractor(True,1,SimpleNamespace(messages=SimpleNamespace(create=create)))
        extractor.reserve_call=lambda:False
        self.assertEqual(extractor.extract(TARGET,PAPER)['status'],'awaiting_extraction')
        self.assertEqual(len(calls),0)
        extractor.reserve_call=lambda:True
        self.assertEqual(extractor.extract(TARGET,PAPER)['status'],'review_ready')
        self.assertEqual(extractor.extract(TARGET,PAPER)['status'],'awaiting_extraction')
        self.assertEqual(len(calls),1)
        payload=json.loads(calls[0]['messages'][0]['content'])
        self.assertEqual(payload['entity']['entity_type'],'biomarker')
        self.assertEqual(payload['source_url'],PAPER['url'])
    def test_public_endpoint_hides_unpublished_extractions(self):
        from flask import Flask
        from living_research.routes import blueprint
        with TemporaryDirectory() as directory:
            database=str(Path(directory)/'test.sqlite3')
            store=Store(database)
            Monitor(store,providers={'pubmed':Provider()},extractor=Extractor()).run([TARGET],only=[TARGET['id']])
            proposal=store.all('proposal')[0]
            app=Flask(__name__);app.register_blueprint(blueprint)
            with patch.dict('os.environ',{'CLARITY_RESEARCH_DATABASE_URL':database}):
                response=app.test_client().get('/api/living-research/entity:apob')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json['updates'],[])
                self.assertEqual(response.json['updates_pending_review'],1)
                review(store,proposal['id'],'Reviewer','Source checked.',True)
                publish(store,proposal['id'])
                response=app.test_client().get('/api/living-research/entity:apob')
                self.assertEqual(len(response.json['updates']),1)
                self.assertEqual(response.json['updates_pending_review'],0)
            store.close()
    def test_repeat_run_is_idempotent(self):
        first=self.monitor().run([TARGET],only=[TARGET['id']])
        second=self.monitor().run([TARGET],only=[TARGET['id']])
        self.assertEqual(first['proposals'],1);self.assertEqual(second['proposals'],0)
        self.assertEqual(len(self.store.all('proposal')),1)
        self.assertEqual(self.store.all('proposal')[0]['status'],'review_ready')
    def test_failure_does_not_advance_watermark(self):
        self.monitor().run([TARGET],only=[TARGET['id']])
        before=self.store.get('cursor','entity:apob|pubmed')
        result=self.monitor(Provider(fail=True)).run([TARGET],only=[TARGET['id']])
        self.assertEqual(result['status'],'partial_failure')
        self.assertEqual(before,self.store.get('cursor','entity:apob|pubmed'))
        self.assertEqual(self.store.get('target','entity:apob')['last_status'],'partial_failure')
    def test_single_worker_lease(self):
        self.assertTrue(self.store.acquire('first'))
        self.assertFalse(self.store.acquire('second'))
        with self.assertRaises(RuntimeError):self.monitor().run([TARGET])
        self.store.release('first')
        self.assertTrue(self.store.acquire('second'))
    def test_approval_publication_and_no_grade_change(self):
        self.monitor().run([TARGET],only=[TARGET['id']])
        p=self.store.all('proposal')[0]
        with self.assertRaises(ValueError):publish(self.store,p['id'])
        review(self.store,p['id'],'Test reviewer','Checked the source.',True)
        output=publish(self.store,p['id'])
        self.assertEqual(output['version'],1);self.assertFalse(output['clinical_grade_changed'])
        self.assertEqual(len(output['updates']),1)
        with self.assertRaises(ValueError):publish(self.store,p['id'])
    def test_stale_baseline_requires_new_review(self):
        other={**PAPER,'pmid':'456','source_id':'456','doi':'10.1/other'}
        self.monitor(Provider(records=[PAPER,other])).run([TARGET],only=[TARGET['id']])
        a,b=self.store.all('proposal')
        review(self.store,a['id'],'Reviewer','Checked.',True);review(self.store,b['id'],'Reviewer','Checked.',True)
        publish(self.store,a['id'])
        with self.assertRaises(ValueError):publish(self.store,b['id'])
        rebased=rebase(self.store,b['id']);self.assertEqual(rebased['status'],'review_ready');self.assertNotIn('review',rebased)
    def test_changed_record_supersedes_unpublished_proposal(self):
        self.monitor().run([TARGET],only=[TARGET['id']])
        changed={**PAPER,'title':'Corrected ApoB in adults'}
        self.monitor(Provider(records=[changed])).run([TARGET],only=[TARGET['id']])
        self.assertEqual(sorted(p['status'] for p in self.store.all('proposal')),['review_ready','superseded'])
    def test_metadata_change_reuses_extraction_but_changed_text_does_not(self):
        self.monitor().run([TARGET],only=[TARGET['id']])
        metadata={**PAPER,'journal':'Updated journal metadata'}
        second=self.monitor(Provider(records=[metadata]))
        second.run([TARGET],only=[TARGET['id']])
        self.assertEqual(second.extractor.calls,0)
        self.assertTrue(next(p for p in self.store.all('proposal') if p['status']=='review_ready')['extraction']['cache_hit'])
        third=self.monitor(Provider(records=[{**metadata,'abstract':PAPER['abstract']+' Updated follow-up.'}]))
        third.run([TARGET],only=[TARGET['id']])
        self.assertEqual(third.extractor.calls,1)
    def test_context_change_does_not_reuse_extraction(self):
        self.monitor().run([TARGET],only=[TARGET['id']])
        next_monitor=self.monitor()
        next_monitor.run([{**TARGET,'population':'Children'}],only=[TARGET['id']])
        self.assertEqual(next_monitor.extractor.calls,1)
    def test_disabled_target_does_not_consume_queued_ai_calls(self):
        Monitor(self.store,providers={'pubmed':Provider()},extractor=AIExtractor(False)).run([TARGET],only=[TARGET['id']])
        extractor=Extractor()
        Monitor(self.store,{'targets':{TARGET['id']:{'enabled':False}}},providers={'pubmed':Provider()},extractor=extractor).run([TARGET])
        self.assertEqual(extractor.calls,0)
    def test_pubmed_preserves_inline_text_and_corrections(self):
        xml='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Study of <i>ApoB</i></ArticleTitle><Abstract><AbstractText>Measured <b>100</b> adults.</AbstractText></Abstract></Article><CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn"><PMID>456</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation></PubmedArticle></PubmedArticleSet>'
        parsed=PubMed.parse(xml)[0]
        self.assertEqual(parsed['title'],'Study of ApoB');self.assertIn('100 adults',parsed['abstract']);self.assertEqual(parsed['corrections'][0]['pmid'],'456')
    def test_large_windows_are_split_without_losing_days(self):
        class Busy:
            def search(self,target,since,until,limit):
                if since!=until:raise IncompleteSearch()
                return [since],{'complete':True,'since':since,'until':until}
        records,audit=retrieve_window(Busy(),TARGET,'2026-09-01','2026-09-03',1)
        self.assertEqual(records,['2026-09-01','2026-09-02','2026-09-03']);self.assertTrue(audit['complete'])

if __name__=='__main__':unittest.main()
