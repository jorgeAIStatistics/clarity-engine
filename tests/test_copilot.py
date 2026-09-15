import json,time,unittest
from unittest.mock import patch
from evidence.matcher import documents,match
from evidence.service import CATALOG
from evidence.feedback import token_for,record_feedback,improvement_signals
from living_research.store import Store
from living_research.priority import priority_score
QUESTION='We are studying apolipoprotein B (ApoB), LDL cholesterol and HbA1c in adults, focusing on cardiovascular events and how biomarker associations differ from clinical utility.'

class CopilotTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.index=documents(CATALOG['entities']);cls.result=match(QUESTION,cls.index)
 def test_success_question_is_structured_without_invented_population(self):
  q=self.result['copilot']['question'];self.assertEqual(q['population'],['adults']);self.assertEqual(q['outcomes'],['cardiovascular events'])
  self.assertEqual({e['name'] for e in q['primary_concepts']},{'ApoB','LDL-C','HbA1c'})
  self.assertEqual({a['id'] for a in q['focus']},{'association','utility'})
 def test_utility_not_inferred_from_drug_trials(self):
  c=self.result['copilot'];groups={g['id']:g for g in c['groups']}
  self.assertTrue(groups['association']['study_ids']);self.assertTrue(groups['incremental']['study_ids']);self.assertFalse(groups['utility']['study_ids'])
  self.assertEqual(groups['utility']['status'],'retrieval_gap');self.assertTrue(c['tensions']);self.assertTrue(c['guidance'])
 def test_every_synthesized_finding_has_retained_source(self):
  sources={s['id']:s for s in self.result['studies']}
  for group in self.result['copilot']['groups']:
   for f in group['findings']:
    self.assertIn(f['study_id'],sources);self.assertTrue(any(f['quote']==x['quote'] and f['effect']==x['effect'] for x in sources[f['study_id']]['findings']))
 def test_matrix_counts_and_bridges_follow_records(self):
  for row in self.result['copilot']['landscape']:
   for cell in row['cells']:self.assertEqual(cell['count'],sum(row['entity_id'] in s['entity_ids'] and cell['angle'] in s['angles'] for s in self.result['studies']))
  self.assertTrue(any(b['entity_type']=='diagnostic' for b in self.result['copilot']['bridges']))
 def test_broad_tokens_do_not_create_tangential_hits(self):
  r=match('Health research about human clinical evidence and outcomes',self.index)
  self.assertFalse(r['entities']);self.assertFalse(r['studies'])
 def test_mapped_table_uses_same_question_pipeline(self):
  r=match('topic: ApoB; outcome: cardiovascular events; context: adults\ntopic: HbA1c; outcome: diabetes diagnosis; context: prospective cohort',self.index)
  self.assertTrue(r['copilot']['question']['outcomes']);self.assertTrue(r['copilot']['groups'])
 def test_cardiovascular_question_prioritizes_coronary_over_diabetes(self):
  group=next(g for g in self.result['copilot']['groups'] if g['id']=='association')
  self.assertTrue('Coronary' in group['findings'][1]['outcome'])
 def test_no_agreement_verdict(self):
  self.assertEqual(self.result['agreement_assessment']['supporting'],[]);self.assertEqual(self.result['agreement_assessment']['contradicting'],[])

class FeedbackTests(unittest.TestCase):
 def setUp(self):self.store=Store(':memory:');self.result=match(QUESTION,documents(CATALOG['entities']));self.token=token_for(self.result)
 def tearDown(self):self.store.close()
 def test_feedback_is_coded_minimal_and_replay_safe(self):
  data={'token':self.token,'code':'missing_angle','angle':'utility'}
  self.assertEqual(record_feedback(self.store,data)['status'],'recorded');self.assertEqual(record_feedback(self.store,data)['status'],'already_recorded')
  rows=self.store.all('matcher_feedback');self.assertEqual(len(rows),1);self.assertEqual(set(rows[0]),{'id','code','angle','target_ids','version','created_at'});self.assertNotIn(QUESTION,json.dumps(rows))
 def test_tampering_expiry_and_arbitrary_text_rejected(self):
  for data in [{'token':self.token+'x','code':'helpful','angle':''},{'token':self.token,'code':'my private text','angle':''},{'token':self.token,'code':'missing_angle','angle':''},{'token':self.token,'code':'helpful','angle':'','text':'not allowed'}]:
   with self.assertRaises(ValueError):record_feedback(self.store,data)
  with patch('evidence.feedback.time.time',return_value=time.time()+3700):
   with self.assertRaises(ValueError):record_feedback(self.store,{'token':self.token,'code':'helpful','angle':''})
 def test_only_bounded_recent_signals_change_scheduling_not_grades(self):
  record_feedback(self.store,{'token':self.token,'code':'missing_angle','angle':'utility'})
  signal=improvement_signals(self.store)['entity:apob'];self.assertEqual(signal['priority_boost'],2);self.assertEqual(signal['missing_angles'],['utility'])
  self.assertFalse(improvement_signals(self.store,time.time()+31*86400))
  self.assertLessEqual(priority_score({'feedback_priority_boost':999},0)-priority_score({},0),20)
  self.assertFalse(self.store.all('published'))

class FindingScopeTests(unittest.TestCase):
 def test_shared_publication_keeps_marker_specific_extracts(self):
  result=match('Lipoprotein(a) incremental cardiovascular prediction in adults',documents(CATALOG['entities']))
  record=next(s for s in result['studies'] if s['pmid']=='22797450')
  self.assertEqual([f['effect']['estimate'] for f in record['findings']],[.0016])
 def test_high_sensitivity_crp_is_not_test_accuracy(self):
  from evidence.copilot import record_angles
  self.assertNotIn('accuracy',record_angles({'title':'High sensitivity CRP','_text':'a randomized trial','layer':'interventional'}))
 def test_c_index_findings_not_presented_as_association_effects(self):
  result=match(QUESTION,documents(CATALOG['entities']))
  for group in result['copilot']['groups']:
   if group['id']=='association':self.assertFalse(any('C-index' in f['effect']['measure'] for f in group['findings']))

class ReviewSignalTests(unittest.TestCase):
 def test_recent_rejected_proposals_prioritize_existing_target(self):
  from datetime import datetime,timezone
  store=Store(':memory:')
  try:
   for i in range(8):store.put('proposal',str(i),{'target_id':'entity:apob','status':'rejected','review':{'reviewed_at':datetime.now(timezone.utc).isoformat()}})
   signal=improvement_signals(store)['entity:apob']
   self.assertEqual(signal['corrections'],8);self.assertEqual(signal['priority_boost'],12)
   self.assertFalse(store.all('published'))
  finally:store.close()

class WorkspaceCandidateTests(unittest.TestCase):
 def test_workspace_candidate_window_remains_bounded(self):
  index=documents(CATALOG['entities'])
  result=match(QUESTION,index,study_limit=1000)
  self.assertLessEqual(len(result['studies']),48)
  self.assertGreaterEqual(len(result['studies']),len(match(QUESTION,index)['studies']))

class WorkspaceRouteTests(unittest.TestCase):
 def test_workspace_flag_is_strict_and_uses_larger_bounded_window(self):
  from app import app
  client=app.test_client()
  with patch('evidence.intent_graph.service.run',return_value=match(QUESTION,documents(CATALOG['entities']),study_limit=48)) as graph_run:
   response=client.post('/api/evidence/match',json={'text':QUESTION,'workspace':True})
   self.assertEqual(response.status_code,200)
   graph_run.assert_called_once_with(QUESTION)
   self.assertLessEqual(len(response.json['studies']),48)
   self.assertEqual(client.post('/api/evidence/match',json={'text':QUESTION,'workspace':'yes'}).status_code,400)
   self.assertEqual(client.post('/api/evidence/match',json={'text':QUESTION,'workspace':True,'private_file':'no'}).status_code,400)
