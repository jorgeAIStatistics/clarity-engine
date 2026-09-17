"""What a publish must put in the graph, and what a profile read must get back.

Every finding this project extracts has to land on one of the five layers. Before these tests, a
meta-analysis or systematic review was labelled 'synthesis' — not one of the five — and the
publisher's `if layer in LAYERS` guard then dropped it without a word: six live links to the
RET x selpercatinib pair existed as ABOUT edges that no rollup, heatmap or catalog count could see.
"""
import hashlib
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from evidence_pipeline.schemas.pico import SourceDocument
from evidence_pipeline.extraction.core import source_tokens
from evidence_pipeline.extraction.observations import decode_observations
from evidence.intent_graph import cypher
from evidence.intent_graph.findings import LAYER_BY_DESIGN, SYNTHESIS_DESIGNS, finding_layer, statements

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / 'evidence' / 'intent_graph' / 'registry.json').read_text())
NONE = {'first_token': None, 'last_token': None, 'confidence': None}
POOLED = ("SYNTHETIC TEST ONLY. Pooled safety of selpercatinib in RET-altered cancer\n\n"
          "In a meta-analysis of randomised clinical trials, selpercatinib was associated with grade 3 or "
          "higher adverse events (odds ratio 2.10, 95% CI 1.60 to 2.75).")


def document(text, pmid='90000001'):
    return SourceDocument(id='pmid:' + pmid, kind='abstract', pmid=pmid, pmcid=None, doi=None,
                          source_url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/', version='test',
                          retrieved_at=datetime(2026, 9, 17, tzinfo=timezone.utc), text=text,
                          sha256=hashlib.sha256(text.encode()).hexdigest())


class Tokens:
    def __init__(self, text):
        self.tokens = [t[2] for t in source_tokens(text)]

    def at(self, word, nth=0, length=1):
        hits = [i for i, t in enumerate(self.tokens) if t == word]
        return {'first_token': hits[nth], 'last_token': hits[nth] + length - 1, 'confidence': 0.9}


T = Tokens(POOLED)
SOURCE = document(POOLED)


def observation(**fields):
    base = {k: NONE for k in ('marker', 'target', 'population', 'setting', 'comparator', 'assay', 'measure_quote',
                              'value', 'unit', 'lower', 'upper', 'level', 'threshold', 'threshold_unit', 'n',
                              'p_value', 'statement')}
    base.update(p_operator='not_reported')
    base.update(fields)
    return base


ADVERSE = observation(observation_type='association', measure='odds_ratio', marker=T.at('selpercatinib', 1),
                      target=T.at('adverse', 0, 2), measure_quote=T.at('odds', 0, 2), value=T.at('2.10'),
                      lower=T.at('1.60'), upper=T.at('2.75'), level=T.at('95'))


def record(design='meta_analysis'):
    body = {'study_design': design, 'design_quote': T.at('meta-analysis'), 'observations': [ADVERSE]}
    return dict(decode_observations(body, SOURCE), study_id=SOURCE.id, source=SOURCE.model_dump(mode='json'),
                extracted_at='2026-09-17T00:00:00+00:00', version='biomarker-observations-v2')


class LayerContractTests(unittest.TestCase):
    def test_every_design_places_a_finding_on_one_of_the_five_layers(self):
        """No design may produce a layer outside LAYERS: that is what made findings disappear."""
        finding = record()['findings'][0]
        designs = set(LAYER_BY_DESIGN) | SYNTHESIS_DESIGNS | {'other', 'not_determined', 'unheard_of'}
        for design in sorted(designs):
            self.assertIn(finding_layer(design, finding), cypher.LAYERS, f'{design} escaped the five layers')

    def test_a_pooled_result_sits_on_the_layer_it_pooled(self):
        """The design sentence decides, and it lives in the methods, not beside the number."""
        finding = record()['findings'][0]
        self.assertEqual(finding_layer('meta_analysis', finding, POOLED), 'interventional',
                         'this abstract says in one sentence that it pooled randomised trials')
        accuracy = ('A systematic review and meta-analysis of diagnostic test accuracy studies. '
                    'Randomised trials of treatment were outside its scope.')
        self.assertEqual(finding_layer('meta_analysis', finding, accuracy), 'observational',
                         'trials named in a different sentence must not promote a pooled accuracy review')
        self.assertEqual(finding_layer('meta_analysis', finding, 'A meta-analysis of prospective cohorts.'),
                         'observational', 'a meta-analysis of cohorts is observational evidence')

    def test_publishing_a_meta_analysis_links_it_to_an_entity_and_a_rollup(self):
        written, linked = statements(record(), REGISTRY)
        self.assertIn('compound:selpercatinib', linked)
        queries = [q for q, _ in written]
        supported = [p for q, p in written if 'SUPPORTED_BY' in q and 'MERGE' in q]
        self.assertTrue(supported, 'a published finding with no rollup edge is invisible to the product')
        self.assertEqual({p['layer'] for p in supported}, {'interventional'})
        self.assertTrue(any('ABOUT' in q for q in queries))

    def test_a_finding_stores_its_own_layer_and_says_it_is_pooled(self):
        """Stored on the node, so a stale rollup can never make a published finding look layerless."""
        written, _ = statements(record(), REGISTRY)
        node = next(p for q, p in written if 'MERGE (f:Finding' in q)
        self.assertEqual((node['layer'], node['synthesis']), ('interventional', True))
        single, _ = statements(record(design='observational'), REGISTRY)
        plain = next(p for q, p in single if 'MERGE (f:Finding' in q)
        self.assertFalse(plain['synthesis'], 'only a review or meta-analysis is a synthesis')
        self.assertEqual(plain['layer'], 'observational')

    def test_the_catalog_and_gap_queries_count_the_edge_the_publisher_writes(self):
        """Counting through HAS_LAYER would repeat the bug: it is a rollup, ABOUT is the fact."""
        for query in (cypher.CATALOG_SORT, cypher.GAP_FEATURES):
            self.assertIn('<-[:ABOUT]-(f:Finding)', query)
            self.assertIn('coalesce(e.ephemeral, false) = false', query)
        self.assertIn('n_utility_kind', cypher.GAP_FEATURES)
        self.assertIn('n_utility_layer', cypher.GAP_FEATURES)


@unittest.skipUnless(os.environ.get('CLARITY_GRAPH_TESTS') == '1', 'publish roundtrip needs CLARITY_GRAPH_TESTS=1')
class PublishRoundTripTests(unittest.TestCase):
    """Upsert a finding, then read it back through the route the website calls. Ids start test:."""

    def setUp(self):
        from evidence.intent_graph import store
        self.store = store
        self.session = store.session().__enter__()
        self.entity = dict(id='test:pooled-marker', name='TEST pooled marker', aliases=['selpercatinib'], type='compound')
        cypher.run_all(self.session, cypher.entity_statements(self.entity, registry_version='test'))

    def tearDown(self):
        self.session.run("MATCH (e:Entity {id:'test:pooled-marker'}) OPTIONAL MATCH (e)-[:HAS_LAYER]->(l) DETACH DELETE e,l").consume()
        self.session.run("MATCH (s:Study {id:$id}) OPTIONAL MATCH (s)-[:REPORTS]->(f) DETACH DELETE s,f", id=SOURCE.id).consume()
        self.session.__exit__(None, None, None)

    def test_a_published_finding_comes_back_from_the_profile_route(self):
        from evidence.intent_graph.findings import publish
        linked = publish(record(), [self.entity], self.session)
        self.assertEqual(linked, ['test:pooled-marker'])
        profile = self.store.graph_entity('test:pooled-marker', self.session)
        found = profile['findings']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['layer'], 'interventional', 'the layer must survive the round trip')
        self.assertEqual(found[0]['finding']['kind'], 'association')
        self.assertTrue(found[0]['quote'], 'a finding without its passage is not publishable')
        rolled = {l['layer']: l['n_findings'] for l in profile['layers']}
        self.assertEqual(rolled['interventional'], 1, 'the rollup must see what ABOUT sees')


if __name__ == '__main__':
    unittest.main()
