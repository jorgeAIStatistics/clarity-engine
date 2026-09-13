import json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import cache,db

class ProfileSnapshotTests(unittest.TestCase):
 def test_database_stream_uses_one_query_and_connection(self):
  conn=MagicMock();conn.__enter__.return_value=conn;cur=conn.cursor.return_value.__enter__.return_value
  cur.fetchone.side_effect=[('apob',{'name':'ApoB'}),('creatine',json.dumps({'name':'Creatine'})),None]
  with patch.object(db,'available',return_value=True),patch.object(db,'_connect',return_value=conn) as connect,patch.object(db,'_ensure_schema'):
   result=dict(db.iter_profiles())
  connect.assert_called_once();conn.cursor.assert_called_once_with(name='clarity_profile_index');cur.execute.assert_called_once_with('SELECT slug, profile FROM profiles ORDER BY slug');cur.fetchall.assert_not_called()
  self.assertEqual(result['creatine']['name'],'Creatine')
 def test_database_stream_avoids_per_profile_reads(self):
  database=MagicMock();database.iter_profiles.return_value=iter([('test',{'name':'Test'})])
  with tempfile.TemporaryDirectory() as directory,patch.object(cache,'CACHE_DIR',directory),patch.object(cache,'_db',return_value=database):self.assertEqual(dict(cache.iter_profiles()),{'test':{'name':'Test'}})
  database.get.assert_not_called()
 def test_partial_database_failure_retains_completed_records(self):
  def rows():
   yield 'valid',{'name':'Database version'}
   raise ConnectionError('test failure')
  database=MagicMock();database.iter_profiles.side_effect=rows
  with tempfile.TemporaryDirectory() as directory:
   Path(directory,'valid.json').write_text('{"name":"Older file"}');Path(directory,'other.json').write_text('{"name":"Other"}');Path(directory,'invalid.json').write_text('{')
   with patch.object(cache,'CACHE_DIR',directory),patch.object(cache,'_db',return_value=database):self.assertEqual(dict(cache.iter_profiles()),{'valid':{'name':'Database version'},'other':{'name':'Other'}})
  database.iter_profiles.assert_called_once();database.get.assert_not_called()
 def test_non_profile_cache_files_are_not_indexed(self):
  with tempfile.TemporaryDirectory() as directory:
   for name in ['retrieval','citations','translations','creatine']:
    Path(directory,name+'.json').write_text(json.dumps({'name':name,'claims':[]}))
   with patch.object(cache,'CACHE_DIR',directory),patch.object(cache,'_db',return_value=None):self.assertEqual(list(dict(cache.iter_profiles())),['creatine'])
