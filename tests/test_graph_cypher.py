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
        self.assertGreaterEqual(report['cases'],23)
        self.assertEqual((report['precision'],report['recall'],report['forbidden'],report['mismatches']),(1.0,1.0,[],[]))

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
        graph=[dict(id='biomarker:ca-125',name='CA-125',kind='Biomarker',type='biomarker',aliases=['CA-125','CA125'],last_extracted_at='2026-09-14T10:00:00',findings=3,layers=['observational'],sentences=[json.dumps(['Automated reading: 3 classification findings for CA-125 and ovarian cancer (AUC 0.8). Not expert-reviewed.'])],studies=4),
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
        self.assertTrue(rows[0]['summary'].startswith('Automated reading'))
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
