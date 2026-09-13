import unittest
from unittest.mock import patch
from evidence.library import build_library

class LibraryTests(unittest.TestCase):
    def test_unified_library_keeps_domains_and_deduplicates_cached_names(self):
        p={'name':'Example compound','category':'supplement','claims':[{'outcome':'Strength','studies':[]}],'generated_at':'2026-09-01'}
        with patch('cache.list_cached',return_value=['example','example-copy','internal']),patch('cache.get',side_effect=lambda k,**_:p if k!='internal' else {}):
            result=build_library()
        compounds=[e for e in result['entries'] if e['entity_type']=='intervention']
        self.assertEqual(len(compounds),1)
        self.assertEqual(compounds[0]['path'],'/compound/example-compound')
        self.assertFalse(compounds[0]['available'])
        self.assertEqual(result['counts']['biomarker'],14)
        self.assertEqual(len({e['id'] for e in result['entries']}),len(result['entries']))
