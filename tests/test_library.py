import unittest
from unittest.mock import patch
from evidence.library import build_library


class Unreachable(Exception):
    """What the Neo4j driver raises when the database is asleep."""


class LibraryTests(unittest.TestCase):
    def test_unified_library_keeps_domains_and_deduplicates_cached_names(self):
        p = {'name': 'Example compound', 'category': 'supplement', 'claims': [{'outcome': 'Strength', 'studies': []}], 'generated_at': '2026-09-01'}
        with patch('cache.iter_profiles', return_value=iter([('example', p), ('example-copy', p), ('internal', {})])):
            result = build_library()
        compounds = [e for e in result['entries'] if e['entity_type'] == 'intervention']
        self.assertEqual(len(compounds), 1)
        self.assertEqual(compounds[0]['path'], '/compound/example-compound')
        self.assertFalse(compounds[0]['available'])
        self.assertEqual(len({e['id'] for e in result['entries']}), len(result['entries']))

    def test_the_biomarker_count_is_the_curated_profiles_plus_the_graph(self):
        """It read 14 — the curated profiles alone — whenever the graph did not answer.

        The old assertion froze that degraded number as the expected one, so the index shrinking to
        fourteen while ninety graph cards sat below it was a passing test rather than a bug.
        """
        with patch('cache.iter_profiles', return_value=iter([])):
            result = build_library()
        rows = [e for e in result['entries'] if e['entity_type'] == 'biomarker']
        curated = [e for e in rows if not e['id'].startswith('graph:')]
        self.assertEqual(len(curated), 14, 'the curated biomarker profiles')
        self.assertGreater(len(rows), 90, 'the index must count the graph profiles it lists')
        self.assertEqual(result['counts']['biomarker'], len(rows))
        self.assertTrue(any(e['name'] == 'IL-18' for e in rows))

    def test_the_count_does_not_collapse_when_the_graph_is_unreachable(self):
        with patch('cache.iter_profiles', return_value=iter([])), \
             patch('evidence.intent_graph.store.graph_library', side_effect=Unreachable('asleep')):
            result = build_library()
        self.assertGreater(result['counts']['biomarker'], 90, 'the published snapshot keeps the shelf stocked')

    def test_every_routable_entity_gets_an_address(self):
        """A gene and the protein it encodes share a name; neither may lose its page to the other.

        The first fix only covered the gene arriving second. When the protein arrived second it
        overwrote the gene's row outright, which is why RET still had no page after the other six
        genes were given suffixed addresses.
        """
        from evidence.library import graph_entries
        from evidence.intent_graph import snapshot
        feed = snapshot.library()
        if not feed:
            self.skipTest('no published snapshot in this checkout')
        rows = graph_entries([])
        routed = {r['id'].split('graph:', 1)[1] for r in rows}
        routable = {'Biomarker', 'Gene', 'Variant', 'Protein', 'Test', 'Assay', 'PrecisionContext'}
        missing = [g['id'] for g in feed if g.get('kind') in routable and g['id'] not in routed]
        self.assertEqual(missing, [], 'these entities exist in the graph and no URL reaches them')

        paths = {r['path'] for r in rows}
        self.assertEqual(len(paths), len(rows), 'two entities share one address')
        for gene in ('egfr', 'ret', 'braf', 'kras', 'alk', 'ros1', 'pik3ca'):
            self.assertIn(f'/biomarkers/{gene}-gene', paths, f'{gene} gene lost its page to the protein')
            self.assertIn(f'/biomarkers/{gene}', paths, f'{gene} the protein lost its plain address')
