import os,tempfile,unittest
from evidence_pipeline.state import State
from evidence.intent_graph.jobs import STAGES,GAP_QUERY,MISSES_QUERY,enqueue,pending,run_job,rank_gaps

class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.state=State(os.path.join(self.folder.name,'state.sqlite3'))
    def tearDown(self):
        self.state.close();self.folder.cleanup()

    def handlers(self,calls,fail_at=None):
        def make(stage):
            def run(ctx,job):
                calls.append(stage)
                if stage==fail_at:raise RuntimeError('neo4j_unavailable')
                ctx[stage]=True;return {'stage_ok':True}
            return run
        return {stage:make(stage) for stage in STAGES}

    def test_stages_run_in_order_and_record_history(self):
        calls=[];job=run_job(self.state,enqueue(self.state,'biomarker:ca-125','no utility findings',2.5),self.handlers(calls))
        self.assertEqual((calls,job['status']),(list(STAGES),'done'))
        self.assertEqual([h['stage'] for h in self.state.get('graph_job','graph-job:biomarker:ca-125')['history']],list(STAGES))

    def test_a_failed_job_resumes_at_the_failed_stage(self):
        calls=[];job=run_job(self.state,enqueue(self.state,'biomarker:cea','gap',1),self.handlers(calls,fail_at='upsert'))
        self.assertEqual((job['status'],job['stage'],job['error']),('failed','upsert','neo4j_unavailable'))
        requeued=enqueue(self.state,'biomarker:cea','asked again',3)
        self.assertEqual((requeued['status'],requeued['stage'],requeued['priority'],requeued['reasons']),('queued','upsert',3,['asked again','gap']))
        calls.clear();job=run_job(self.state,requeued,self.handlers(calls))
        self.assertEqual((calls,job['status']),(['upsert','synthesize','publish'],'done'))
        self.assertTrue(job['context']['extract'])

    def test_pending_orders_by_priority(self):
        enqueue(self.state,'biomarker:a','x',1);enqueue(self.state,'biomarker:b','x',4);enqueue(self.state,'biomarker:c','x',2)
        self.assertEqual([j['entity_id'] for j in pending(self.state,2)],['biomarker:b','biomarker:c'])

class GapRankerTests(unittest.TestCase):
    def test_thin_domains_and_indexed_but_unmined_markers_rank_above_empty_names(self):
        rows=[dict(id='precision_context:ret-selpercatinib',name='RET × selpercatinib',kind='PrecisionContext',utility_findings=0,findings=0,asked=0,dead_letters=0,studies=0),
              dict(id='test:amyloid-pet',name='amyloid PET',kind='Test',utility_findings=0,findings=0,asked=0,dead_letters=0,studies=0),
              dict(id='biomarker:ca-125',name='CA-125',kind='Biomarker',utility_findings=0,findings=0,asked=0,dead_letters=0,studies=3),
              dict(id='biomarker:quiet',name='Quiet marker',kind='Biomarker',utility_findings=0,findings=0,asked=0,dead_letters=0,studies=0)]
        ranked=rank_gaps(rows)
        self.assertEqual([r['name'] for r in ranked],['amyloid PET','RET × selpercatinib','CA-125','Quiet marker'])
        self.assertIn('thin domain: precision pair',[x for r in ranked for x in r['reasons']])
        self.assertIn('3 linked publications but no typed finding',ranked[2]['reasons'])

    def test_asked_entities_with_empty_utility_layers_rank_first(self):
        rows=[dict(id='biomarker:apob',name='ApoB',kind='Biomarker',utility_findings=0,findings=4,asked=0,dead_letters=0,studies=0),
              dict(id='biomarker:il-18',name='IL-18',kind='Biomarker',utility_findings=0,findings=0,asked=3,dead_letters=0,studies=0),
              dict(id='biomarker:ldl-c',name='LDL-C',kind='Biomarker',utility_findings=2,findings=9,asked=1,dead_letters=0,studies=0),
              dict(id='biomarker:chromogranin-a',name='Chromogranin A',kind='Biomarker',utility_findings=0,findings=0,asked=0,dead_letters=6,studies=0)]
        ranked=rank_gaps(rows,[dict(name='Galectin-3',type='biomarker',asked=2)])
        self.assertEqual([r['name'] for r in ranked],['IL-18','Galectin-3','LDL-C','ApoB','Chromogranin A'])
        self.assertEqual(ranked[0]['reasons'],['asked in 3 recent questions','no interventional or guideline findings','no typed findings in any layer'])
        self.assertEqual((ranked[1]['kind'],ranked[1]['id']),('matcher_miss',None))
        self.assertEqual(ranked[-1]['score'],0.5)

    def test_gap_queries_count_questions_through_mentions_only(self):
        self.assertIn('(q:Question)-[:MENTIONS]->(e)',GAP_QUERY)
        self.assertIn('(q:Question)-[:MENTIONS]->(t:Entity {ephemeral:true})',MISSES_QUERY)
        for query in (GAP_QUERY,MISSES_QUERY):self.assertNotIn('RELATED_TO',query)
