import copy,json,unittest
from pathlib import Path
from evidence.service import CATALOG
from evidence.provenance import validate_enrichment
from evidence.matcher import documents,match

SNAPSHOT=json.loads(Path('evidence/source_snapshot.json').read_text())
class EnrichmentTests(unittest.TestCase):
 def test_all_sources_and_estimates_are_traceable(self):self.assertTrue(validate_enrichment(CATALOG,SNAPSHOT))
 def changed(self):
  c=copy.deepcopy(CATALOG);s=next(s for e in c['entities'] for s in e['studies'] if s.get('findings'));return c,s
 def test_changed_quote_rejected(self):
  c,s=self.changed();s['findings'][0]['source_span']['start']+=1
  with self.assertRaises(ValueError):validate_enrichment(c,SNAPSHOT)
 def test_invented_numeric_value_rejected(self):
  c,s=self.changed();s['findings'][0]['effect'].update(estimate=1.055,lower=1.03,upper=1.06)
  with self.assertRaises(ValueError):validate_enrichment(c,SNAPSHOT)
 def test_false_review_rejected(self):
  c,s=self.changed();s['extraction']['human_verified']=True
  with self.assertRaises(ValueError):validate_enrichment(c,SNAPSHOT)
 def test_new_entities_populated_and_matchable(self):
  index=documents(CATALOG['entities']);result=match('Cystatin C and creatinine kidney function risk reclassification',index)
  self.assertIn('Cystatin C',[e['name'] for e in result['entities']]);self.assertTrue(any(s['pmid']=='24004120' for s in result['studies']))
  for id in ['non-hdl-c','cystatin-c','msi-pembrolizumab']:self.assertTrue(next(e for e in CATALOG['entities'] if e['id']==id)['studies'])

 def test_renal_egfr_does_not_expand_to_oncology(self):
  from evidence.matcher import expanded_tokens
  t=expanded_tokens('eGFR creatinine kidney function');self.assertIn('glomerular',t);self.assertNotIn('epidermal',t)
  self.assertIn('epidermal',expanded_tokens('EGFR mutated NSCLC'))
