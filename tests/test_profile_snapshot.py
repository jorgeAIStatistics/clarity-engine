import json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import cache,db

class ProfileSnapshotTests(unittest.TestCase):
 def test_database_index_uses_one_query_and_connection(self):
  conn=MagicMock();conn.__enter__.return_value=conn;cur=conn.cursor.return_value.__enter__.return_value
  cur.fetchall.return_value=[('apob',{'name':'ApoB'}),('creatine',json.dumps({'name':'Creatine'}))]
  with patch.object(db,'available',return_value=True),patch.object(db,'_connect',return_value=conn) as connect,patch.object(db,'_ensure_schema'):
   result=db.profile_snapshot()
  connect.assert_called_once();cur.execute.assert_called_once_with('SELECT slug, profile FROM profiles ORDER BY slug')
  self.assertEqual(result['creatine']['name'],'Creatine')
 def test_database_snapshot_avoids_per_profile_reads(self):
  database=MagicMock();database.profile_snapshot.return_value={'test':{'name':'Test'}}
  with patch.object(cache,'_db',return_value=database):self.assertEqual(cache.profile_snapshot(),{'test':{'name':'Test'}})
  database.get.assert_not_called()
 def test_failed_database_falls_back_once_and_skips_invalid_json(self):
  database=MagicMock();database.profile_snapshot.return_value=None
  with tempfile.TemporaryDirectory() as directory:
   Path(directory,'valid.json').write_text('{"name":"Valid"}');Path(directory,'invalid.json').write_text('{')
   with patch.object(cache,'CACHE_DIR',directory),patch.object(cache,'_db',return_value=database):self.assertEqual(cache.profile_snapshot(),{'valid':{'name':'Valid'}})
  database.profile_snapshot.assert_called_once();database.get.assert_not_called()
