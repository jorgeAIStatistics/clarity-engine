"""When the graph cannot be read, a page must still render — and must say what it is showing.

The engine reads Neo4j on every graph request, so an unreachable database used to blank a profile
and shrink the biomarkers index to its fourteen curated entries. These lock the published snapshot
in as the fallback, and lock in that a snapshot never passes itself off as a live read.
"""
import json
import unittest
from unittest.mock import patch

from evidence.intent_graph import snapshot


class Unreachable(Exception):
    """What the Neo4j driver raises when the database is asleep, in one word."""


def client():
    import app
    return app.app.test_client()


class SnapshotFallbackTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot.load()
        if not self.snapshot:
            self.skipTest('no published snapshot in this checkout')

    def test_the_published_snapshot_covers_the_profiles_the_site_routes_to(self):
        entities = self.snapshot['entities']
        self.assertGreaterEqual(len(entities), 100)
        for entity_id in ('biomarker:il-18', 'biomarker:ca-125', 'biomarker:psa', 'precision_context:ret-selpercatinib'):
            self.assertIn(entity_id, entities, f'{entity_id} would sit on a wake screen')
        il18 = entities['biomarker:il-18']
        self.assertTrue(il18['findings'], 'a snapshot of an empty profile is not worth serving')
        self.assertEqual(il18['entity']['name'], 'IL-18')

    def test_a_profile_still_answers_when_the_graph_is_unreachable_and_says_so(self):
        with patch('evidence.intent_graph.store.graph_entity', side_effect=Unreachable('asleep')):
            response = client().get('/api/evidence/graph/entity/biomarker:il-18')
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNotNone(body, 'the profile JSON must be defined even when the live read fails')
        self.assertEqual(body['served_from'], 'snapshot')
        self.assertTrue(body['published_at'], 'a snapshot must carry the date it was published')
        self.assertTrue(body['findings'])
        self.assertEqual(response.headers['Cache-Control'], 'private, max-age=15')

    def test_an_unknown_profile_is_still_a_404_not_a_wake_screen(self):
        """A live read that answers 'no such entity' is an answer, and must not reach the snapshot."""
        with patch('evidence.intent_graph.store.graph_entity', return_value=None):
            response = client().get('/api/evidence/graph/entity/biomarker:not-a-real-marker')
        self.assertEqual(response.status_code, 404)

    def test_a_profile_outside_the_snapshot_fails_loudly_and_is_never_cached(self):
        with patch('evidence.intent_graph.store.graph_entity', side_effect=Unreachable('asleep')):
            response = client().get('/api/evidence/graph/entity/biomarker:not-a-real-marker')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'graph_unavailable')
        self.assertEqual(response.headers['Cache-Control'], 'no-store', 'a failure cached is a page blank for a minute')
        self.assertEqual(response.headers['Retry-After'], '10')

    def test_the_index_keeps_its_graph_rows_when_the_graph_is_unreachable(self):
        """Losing them is what made the biomarkers index read as fourteen profiles."""
        from evidence.library import graph_entries
        with patch('evidence.intent_graph.store.graph_library', side_effect=Unreachable('asleep')):
            rows = graph_entries([])
        self.assertGreaterEqual(len(rows), 80)
        self.assertTrue(any(r['name'] == 'IL-18' for r in rows))

    def test_a_slow_read_falls_back_instead_of_making_the_reader_wait(self):
        """A cold Neo4j connection costs seconds. Waiting for it is the spinner the brief names."""
        import time as clock
        from evidence import routes

        def crawl(entity_id):
            clock.sleep(5)
            return {'never': 'returned in time'}

        started = clock.perf_counter()
        with patch('evidence.intent_graph.store.graph_entity', side_effect=crawl), \
                patch.object(routes, 'GRAPH_DEADLINE', 0.2):
            response = client().get('/api/evidence/graph/entity/biomarker:il-18')
        waited = clock.perf_counter() - started
        self.assertLess(waited, 2.0, 'the reader waited for the slow read anyway')
        body = response.get_json()
        self.assertEqual((response.status_code, body['served_from'], body['fallback_reason']), (200, 'snapshot', 'slow'))
        self.assertTrue(body['findings'])

    def test_the_deadline_does_not_steal_a_read_that_arrives_in_time(self):
        from evidence import routes
        with patch('evidence.intent_graph.store.graph_entity', return_value={'version': 'graph-entity-v1', 'entity': {'id': 'biomarker:il-18'}, 'findings': []}), \
                patch.object(routes, 'GRAPH_DEADLINE', 5):
            body = client().get('/api/evidence/graph/entity/biomarker:il-18').get_json()
        self.assertEqual(body['served_from'], 'graph')
        self.assertNotIn('fallback_reason', body)

    def test_a_graph_read_writes_one_structured_line(self):
        with patch('evidence.intent_graph.store.graph_entity', side_effect=Unreachable('asleep')), \
                self.assertLogs('evidence.routes', level='INFO') as logged:
            client().get('/api/evidence/graph/entity/biomarker:il-18')
        line = json.loads(logged.output[-1].split(':', 2)[-1])
        self.assertEqual(line['event'], 'graph_read')
        self.assertEqual(set(line) & {'request_id', 'entity_id', 'cache_hit', 'upstream_ms'},
                         {'request_id', 'entity_id', 'cache_hit', 'upstream_ms'})
        self.assertEqual(line['entity_id'], 'biomarker:il-18')
        self.assertIsInstance(line['upstream_ms'], int)


if __name__ == '__main__':
    unittest.main()
