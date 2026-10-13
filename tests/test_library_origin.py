"""/api/library has to say whether its graph rows came from Neo4j or from the file on disk.

The fallback exists so a cold or unreachable graph does not shrink the index to its curated rows.
It was stamping served_from='graph' either way, so a three-week-old snapshot reached the browser
wearing the live graph's label and no page could show a freshness notice."""
import unittest
from unittest import mock

from evidence import library as library_module


class LibraryOriginTest(unittest.TestCase):
    def _entries(self):
        return [{'id': 'biomarker:her2', 'name': 'HER2', 'kind': 'Biomarker', 'aliases': ['ERBB2'],
                 'findings': 0, 'studies': 0}]

    def test_a_live_read_is_reported_as_the_graph(self):
        with mock.patch('evidence.intent_graph.store.graph_library', return_value=self._entries()):
            rows = library_module.graph_entries([])
        self.assertEqual(library_module.graph_entries.origin, 'graph')
        self.assertIsNone(library_module.graph_entries.published_at)
        self.assertTrue(rows, 'a live read should still produce rows')

    def test_a_fallback_read_is_reported_as_the_snapshot_with_its_date(self):
        with mock.patch('evidence.intent_graph.store.graph_library', side_effect=RuntimeError('unreachable')), \
             mock.patch('evidence.intent_graph.snapshot.library', return_value=self._entries()), \
             mock.patch('evidence.intent_graph.snapshot.published_at', return_value='2026-09-19T20:10:34Z'):
            library_module.graph_entries([])
        self.assertEqual(library_module.graph_entries.origin, 'snapshot')
        self.assertEqual(library_module.graph_entries.published_at, '2026-09-19T20:10:34Z')

    def test_the_payload_carries_the_origin_so_a_page_can_label_it(self):
        with mock.patch('evidence.intent_graph.store.graph_library', side_effect=RuntimeError('unreachable')), \
             mock.patch('evidence.intent_graph.snapshot.library', return_value=self._entries()), \
             mock.patch('evidence.intent_graph.snapshot.published_at', return_value='2026-09-19T20:10:34Z'):
            payload = library_module.build_library()
        self.assertEqual(payload['graph_source'], 'snapshot')
        self.assertEqual(payload['graph_published_at'], '2026-09-19T20:10:34Z')
        self.assertGreater(payload['graph_rows'], 0, 'the fallback still fills the index')

    def test_an_empty_snapshot_leaves_the_index_curated_rather_than_claiming_a_graph_read(self):
        with mock.patch('evidence.intent_graph.store.graph_library', side_effect=RuntimeError('unreachable')), \
             mock.patch('evidence.intent_graph.snapshot.library', return_value=[]), \
             mock.patch('evidence.intent_graph.snapshot.published_at', return_value=None):
            rows = library_module.graph_entries([])
        self.assertEqual(rows, [])
        self.assertEqual(library_module.graph_entries.origin, 'snapshot')


if __name__ == '__main__':
    unittest.main()
