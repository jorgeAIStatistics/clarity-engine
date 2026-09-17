"""Cypher fixtures for the question subgraph. Static checks always run; live checks need
CLARITY_GRAPH_TESTS=1 and Neo4j credentials, and write only ids prefixed test: which they delete."""
import json,os,re,unittest
from unittest.mock import patch
from evidence.intent_graph import cypher
from evidence.intent_graph.intent import ResearchIntent,complete_entities,resolve_alias
from pathlib import Path

IL18='Interleukin-18 as a Potential Biomarker for Radiotherapy-Related Pain in Breast Cancer: Implications for Personalized Pain Management'
FORBIDDEN=('brca','olaparib','her2','trastuzumab','mammograph')
ROOT=Path(__file__).resolve().parents[1]/'evidence'/'intent_graph'

class StaticCypherTests(unittest.TestCase):
    def test_question_queries_start_from_mentions_and_never_expand_neighbours(self):
        for query in (cypher.QUESTION_SUBGRAPH,cypher.COVERAGE_PAYLOAD,cypher.CELL_FINDINGS):
            self.assertTrue(re.match(r'MATCH \(q:Question \{id:\$qid\}\)-\[:MENTIONS\]->\(e',query))
            for expansion in ('RELATED_TO','HAS_CONDITION','MENTIONS_ENTITY','ENCODED_BY','VARIANT_OF','IN_PATHWAY'):self.assertNotIn(expansion,query)
        self.assertIn('a.norm_name = $norm',cypher.RESOLVE_SPAN)
        self.assertIn("Finding {kind:'classification'}",cypher.CLASSIFICATION_FINDINGS)

    def test_identity_fields_are_written_only_when_curated(self):
        node=dict(id='biomarker:il-18',name='IL-18',aliases=['IL-18'],type='biomarker',entity_class='Cytokine (IL-1 family protein)',specimen='Serum or plasma',pathway_note='Background note.')
        identity=next(p for q,p in cypher.entity_statements(node) if 'e.entity_class=' in q)
        self.assertEqual((identity['entity_class'],identity['specimen'],identity['pathway_note']),('Cytokine (IL-1 family protein)','Serum or plasma','Background note.'))
        bare=dict(id='biomarker:x',name='X',aliases=['X'],type='biomarker')
        self.assertFalse(any('entity_class' in q for q,_ in cypher.entity_statements(bare)))

    def test_question_node_keeps_parsed_fields_not_raw_text_by_default(self):
        qid,statements=cypher.question_statements(IL18,{'entities':['IL-18']},['biomarker:il-18'])
        merged=next(p for q,p in statements if q.startswith('MERGE (q:Question'))
        self.assertIsNone(merged['raw'])
        self.assertEqual([p['entity'] for q,p in statements if 'MENTIONS' in q],['biomarker:il-18'])
        _,stored=cypher.question_statements(IL18,{},['biomarker:il-18'],store_text=True)
        self.assertEqual(next(p for q,p in stored if q.startswith('MERGE (q:Question'))['raw'],IL18)

    def test_entity_writes_preserve_reviewed_and_build_alias_nodes(self):
        node=next(n for n in json.loads((ROOT/'registry.json').read_text()) if n['id']=='biomarker:il-18')
        statements=cypher.entity_statements(node)
        self.assertIn("CASE WHEN e.review_state='reviewed'",statements[0][0])
        self.assertEqual(sorted(p['norm'] for q,p in statements if 'EntityAlias' in q),sorted(cypher.norm_name(a) for a in dict.fromkeys(node['aliases'])))
        self.assertEqual(sum('HAS_LAYER' in q for q,_ in statements),5)

class GoldLinkingTests(unittest.TestCase):
    """MENTIONS linking on the gold set with the deterministic alias path (runs in CI without keys)."""
    def test_gold_precision_and_recall(self):
        from evidence.intent_graph.evaluate import load,mentions
        report=mentions(*load())
        self.assertGreaterEqual(report['cases'],26)
        self.assertEqual((report['precision'],report['recall'],report['forbidden'],report['mismatches']),(1.0,1.0,[],[]))

    def test_one_acronym_three_objects_stay_apart(self):
        """EGFR the protein, EGFR the gene and an EGFR variant are asked for by name in the gold set."""
        from evidence.intent_graph.evaluate import load
        cases,_=load()
        wanted={'biomarker:egfr','gene:egfr','variant:egfr-activating-mutation','gene:il18'}
        asked={e for c in cases for e in c['expected']}
        self.assertEqual(wanted-asked,set(),'a gold case naming each object was removed')
        egfr=[c for c in cases if c['expected']==['gene:egfr']]
        self.assertTrue(egfr and 'biomarker:egfr' in egfr[0]['forbidden'],'the gene case must forbid the protein')

@unittest.skipUnless(os.environ.get('CLARITY_GRAPH_TESTS')=='1','live Neo4j Cypher fixtures need CLARITY_GRAPH_TESTS=1')
class LiveCypherTests(unittest.TestCase):
    def setUp(self):
        from evidence.intent_graph import store
        self.session=store.session().__enter__()
        people=[dict(id='test:il-18',name='TEST IL-18',aliases=['TEST IL-18','TESTIL18'],type='biomarker'),dict(id='test:brca1',name='TEST BRCA1',aliases=['TEST BRCA1'],type='gene'),
                dict(id='test:her2',name='TEST HER2',aliases=['TEST HER2'],type='biomarker'),dict(id='test:mammography',name='TEST mammography',aliases=['TEST mammography'],type='test'),
                dict(id='test:olaparib',name='TEST olaparib',aliases=['TEST olaparib'],type='compound'),dict(id='test:trastuzumab',name='TEST trastuzumab',aliases=['TEST trastuzumab'],type='compound')]
        for node in people:cypher.run_all(self.session,cypher.entity_statements(node,registry_version='test'))
        for other in people[1:]:
            # Popular same-disease neighbours are linked on purpose; the question subgraph must still exclude them.
            cypher.run_all(self.session,cypher.relation_statements(dict(id='test:il-18',related=[dict(id=other['id'],reason='same_population')]),{n['id'] for n in people}))
        self.qid,statements=cypher.question_statements('TEST '+IL18,{'entities':['TEST IL-18']},['test:il-18'])
        cypher.run_all(self.session,statements)
    def tearDown(self):
        self.session.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'test:' OPTIONAL MATCH (e)-[:HAS_ALIAS|HAS_LAYER]->(x) DETACH DELETE x").consume()
        self.session.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'test:' DETACH DELETE e").consume()
        self.session.run('MATCH (q:Question {id:$qid}) DETACH DELETE q',qid=self.qid).consume()
        self.session.__exit__(None,None,None)
    def test_il18_question_subgraph_excludes_hijack_candidates(self):
        rows=self.session.run(cypher.QUESTION_SUBGRAPH,qid=self.qid).data()
        names={row['e']['name'].lower() for row in rows}
        self.assertEqual(names,{'test il-18'})
        for word in FORBIDDEN:self.assertFalse(any(word in n for n in names))
        coverage=self.session.run(cypher.COVERAGE_PAYLOAD,qid=self.qid).data()
        self.assertEqual({r['entity_id'] for r in coverage},{'test:il-18'});self.assertEqual(len(coverage),5)
    def test_alias_resolution_by_normalized_span(self):
        rows=self.session.run(cypher.RESOLVE_SPAN,norm=cypher.norm_name('testil18')).data()
        self.assertEqual([r['e']['id'] for r in rows],['test:il-18'])

class LibraryAndRouteTests(unittest.TestCase):
    def test_library_adds_graph_biomarkers_missing_from_the_catalog(self):
        from evidence.library import graph_entries
        graph=[dict(id='biomarker:ca-125',name='CA-125',kind='Biomarker',type='biomarker',aliases=['CA-125','CA125'],last_extracted_at='2026-09-14T10:00:00',findings=3,layers=['observational'],kinds=['classification','classification','discrimination'],utility_findings=0,sentences=[json.dumps(['Automated reading: 3 classification findings for CA-125 and ovarian cancer (AUC 0.8). Not expert-reviewed.'])],studies=4),
               dict(id='biomarker:apob',name='ApoB',kind='Biomarker',type='biomarker',aliases=['ApoB'],last_extracted_at=None,findings=0,layers=[],sentences=[],studies=2)]
        with patch('evidence.intent_graph.store.graph_library',return_value=graph):
            rows=graph_entries([{'name':'ApoB','aliases':['Apolipoprotein B']}])
        self.assertEqual([r['path'] for r in rows],['/biomarkers/ca-125'])
        variant=dict(id='variant:egfr-activating-mutation',name='EGFR activating mutation',kind='Variant',type='variant',aliases=['EGFR mutation'],last_extracted_at=None,findings=2,layers=['observational'],sentences=[],studies=8)
        # A curated precision-oncology profile carrying the alias "EGFR mutation" is a different
        # object from the variant entity, so it must not hide it from the index.
        with patch('evidence.intent_graph.store.graph_library',return_value=[*graph,variant]):
            widened=graph_entries([{'name':'ApoB','aliases':['Apolipoprotein B']},{'name':'EGFR-mutant NSCLC','aliases':['EGFR mutation']}])
        self.assertEqual(sorted((r['category'],r['path']) for r in widened),[('Molecular marker','/biomarkers/ca-125'),('Variant','/biomarkers/egfr-activating-mutation')])
        others=[dict(id='test:amyloid-pet',name='amyloid PET imaging',kind='Test',type='test',aliases=['amyloid PET'],last_extracted_at=None,findings=0,layers=[],sentences=[],studies=0),
                dict(id='test:low-dose-ct-lung-screening',name='low-dose CT lung cancer screening',kind='Test',type='test',aliases=['LDCT screening'],last_extracted_at=None,findings=0,layers=[],sentences=[],studies=0),
                dict(id='precision_context:ret-selpercatinib',name='RET-altered cancer × selpercatinib',kind='PrecisionContext',type='precision_context',aliases=['selpercatinib'],last_extracted_at=None,findings=1,layers=['interventional'],sentences=[],studies=2)]
        with patch('evidence.intent_graph.store.graph_library',return_value=others):
            routed=graph_entries([])
        self.assertEqual(sorted((r['entity_type'],r['path']) for r in routed),
                         [('diagnostic','/diagnostics/amyloid-pet'),('precision_oncology','/precision-medicine/ret-selpercatinib'),('screening','/screening/low-dose-ct-lung-screening')])
        self.assertEqual((rows[0]['coverage'],rows[0]['maturity']),({'linked_studies':4,'outcomes':0,'quantified_outcomes':3},'Graph profile · automated'))
        self.assertEqual((rows[0]['finding_kinds'],rows[0]['utility_indexed']),({'classification':2,'discrimination':1},False))
        self.assertTrue(rows[0]['summary'].startswith('Automated reading'))
    def test_api_responses_are_never_shared_cached_and_failures_are_never_cached(self):
        from app import app
        client=app.test_client()
        with patch('evidence.intent_graph.store.graph_entity',return_value={'version':'graph-entity-v1','entity':{'id':'biomarker:ca-125'}}):
            ok=client.get('/api/evidence/graph/entity/biomarker:ca-125',headers={'Origin':'https://clarityevidence.com'})
        # The body carries one origin's CORS header, so only that browser may cache it.
        self.assertEqual(ok.headers['Cache-Control'],'private, max-age=60')
        with patch('evidence.intent_graph.store.graph_entity',return_value=None):
            missing=client.get('/api/evidence/graph/entity/biomarker:nothing')
        with patch('evidence.intent_graph.store.graph_entity',side_effect=RuntimeError('neo4j_unavailable')):
            broken=client.get('/api/evidence/graph/entity/biomarker:ca-125')
        self.assertEqual((missing.status_code,missing.headers['Cache-Control']),(404,'no-store'))
        self.assertEqual((broken.status_code,broken.headers['Cache-Control']),(503,'no-store'))
        with patch('evidence.intent_graph.store.graph_stats',return_value={'entities':1}):
            stats=client.get('/api/evidence/graph/stats')
        self.assertNotIn('public',stats.headers['Cache-Control'])

    def test_a_next_step_is_stored_against_its_question_and_expires_with_it(self):
        from app import app
        from evidence.intent_graph import cypher
        client=app.test_client()
        step={'question_id':'question:'+'a'*24,'title':'Test whether ApoB-guided care changes events','design':'Randomized comparison',
              'population':'adults without ASCVD','outcome':'cardiovascular events','comparator':'LDL-C-guided care',
              'why':'the utility rung is empty','rung':'utility','entity_ids':['biomarker:apob','not an id']}
        with patch('evidence.intent_graph.store.save_next_step',return_value='nextstep:abc') as save:
            ok=client.post('/api/evidence/graph/next-step',json=step)
        self.assertEqual((ok.status_code,ok.json['stored'],ok.headers['Cache-Control']),(200,True,'no-store'))
        self.assertEqual(save.call_args[0][1]['entity_ids'],['biomarker:apob'],'ids that are not ids are dropped')
        with patch('evidence.intent_graph.store.save_next_step',return_value=None):
            gone=client.post('/api/evidence/graph/next-step',json=step)
        self.assertEqual(gone.status_code,404)
        self.assertEqual(client.post('/api/evidence/graph/next-step',json={**step,'question_id':'nope'}).status_code,400)
        self.assertEqual(client.post('/api/evidence/graph/next-step',json={**step,'design':''}).status_code,400)
        # The design lives exactly as long as the question, and carries its review state.
        _,statements=cypher.next_step_statements('question:'+'a'*24,step)
        merge=next(p for q,p in statements if 'MERGE (s:NextStep' in q)
        self.assertTrue(any("review_state='automated'" in q for q,_ in statements))
        self.assertIn('expires_at',[k for q,_ in statements for k in ('expires_at',) if 'expires_at' in q])
        self.assertEqual(merge['title'],step['title'])

    def test_graph_entity_route(self):
        from app import app
        client=app.test_client()
        with patch('evidence.intent_graph.store.graph_entity',return_value={'version':'graph-entity-v1','entity':{'id':'biomarker:ca-125'}}):
            self.assertEqual(client.get('/api/evidence/graph/entity/biomarker:ca-125').status_code,200)
        with patch('evidence.intent_graph.store.graph_entity',return_value=None):
            self.assertEqual(client.get('/api/evidence/graph/entity/biomarker:nothing').status_code,404)
        self.assertEqual(client.get('/api/evidence/graph/entity/DROP TABLE').status_code,404)
        with patch('evidence.intent_graph.store.graph_entity',side_effect=RuntimeError('neo4j_configuration_missing')):
            self.assertEqual(client.get('/api/evidence/graph/entity/biomarker:ca-125').status_code,503)
