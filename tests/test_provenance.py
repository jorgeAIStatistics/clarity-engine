"""Whose number is this? A review's discussion quotes other papers, and those are not findings.

Three risk ratios belonging to Gogishvili, Baramidze and a third author were published onto the
EGFR page because the decoder could not tell "this paper measured it" from "this paper mentioned
someone who did". The population wording ("patients without EGFR alterations") happened to catch
them afterwards; nothing would have caught a quoted number in a population that did not.
"""
import json
import unittest
from pathlib import Path

from evidence_pipeline.extraction.observations import provenance_of
from evidence.intent_graph.findings import statements

GOLD = json.loads((Path(__file__).parent / 'fixtures' / 'provenance_gold.json').read_text())
REGISTRY = json.loads((Path(__file__).resolve().parents[1] / 'evidence' / 'intent_graph' / 'registry.json').read_text())


class ProvenanceTests(unittest.TestCase):
    def test_the_gold_passages_are_classified_as_written(self):
        wrong = []
        for case in GOLD['cases']:
            got = provenance_of(case['passage'])
            if got != case['expect']:
                wrong.append(f"{case.get('pmid', 'synthetic')}: wanted {case['expect']}, got {got} — {case['why']}")
        self.assertEqual(wrong, [], '\n'.join(wrong))

    def test_nothing_is_primary_by_default(self):
        """A sentence that says nothing about whose result it is must not be promoted."""
        self.assertEqual(provenance_of('Sensitivity was 79% and specificity 85% at a cut-off of 35 U/mL.'), 'unclear')
        self.assertEqual(provenance_of(''), 'unclear')
        self.assertEqual(provenance_of(None), 'unclear')

    def test_a_quoted_hazard_ratio_never_becomes_a_finding_about_the_marker(self):
        """The regression itself: the review's own passage, through the publisher."""
        quoted = next(c for c in GOLD['cases'] if c.get('pmid') == '42444950')
        source = {'id': 'pmid:42444950', 'pmid': '42444950', 'sha256': 'x' * 64,
                  'text': 'SYNTHETIC HOST. ' + quoted['passage']}
        finding = {'id': 'obs:quoted', 'kind': 'effect', 'measure': 'risk_ratio', 'marker': 'EGFR',
                   'target': 'response outcomes', 'population': 'patients with advanced NSCLC',
                   'setting': None, 'comparator': 'chemotherapy', 'assay': None, 'statement': None,
                   'value': 1.9, 'value_raw': '1.9', 'unit': None, 'lower': 1.39, 'upper': 2.62,
                   'level': 95.0, 'threshold': None, 'threshold_unit': None, 'n': None,
                   'p_value': None, 'p_operator': 'not_reported',
                   'provenance': provenance_of(quoted['passage']),
                   'passage': {'start': 0, 'end': 40, 'text': quoted['passage']}}
        record = {'study_id': 'study:x', 'source': source, 'extracted_at': '2026-09-19T00:00:00+00:00',
                  'version': 'test', 'design': {'study_design': 'systematic_review'}, 'findings': [finding]}

        self.assertEqual(finding['provenance'], 'cited', 'the fixture is no longer the quoted passage')
        written, linked = statements(record, REGISTRY)
        self.assertEqual(linked, [], 'a quoted number was attached to a marker page')
        # Creation only: the publisher also emits cleanup statements that DELETE stale edges.
        self.assertFalse([q for q, _ in written if 'MERGE (f)-[:ABOUT]' in q], 'a cited finding must own no entity edge')
        self.assertFalse([q for q, _ in written if 'MERGE (l)-[:SUPPORTED_BY]' in q], 'a cited finding must reach no rollup')
        self.assertFalse([q for q, _ in written if 'MERGE (s)-[r:MENTIONS_ENTITY]' in q], 'and must mention no entity')
        # It is still stored, with its provenance, so the record is not lost.
        node = next(p for q, p in written if 'MERGE (f:Finding' in q)
        self.assertEqual(node['provenance'], 'cited')

        # The same finding, said in this paper's own voice, does link.
        own = dict(finding, provenance='primary')
        _, links = statements(dict(record, findings=[own]), REGISTRY)
        self.assertEqual(links, ['biomarker:egfr'])

    def test_an_unclear_finding_still_links_because_most_abstracts_never_say(self):
        """Excluding unclear would empty the library: nearly every abstract states a result flatly."""
        unclear = [c for c in GOLD['cases'] if c['expect'] == 'unclear' and c.get('pmid')]
        self.assertGreaterEqual(len(unclear), 4, 'the gold set must keep real non-committal passages')


if __name__ == '__main__':
    unittest.main()
