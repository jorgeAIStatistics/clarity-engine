"""Unsupported model claims are excluded without inventing replacements."""

import unittest
from copy import deepcopy
from evidence_pipeline.common import PipelineError
from evidence_pipeline.extraction.grounding import ground_transport
from evidence_pipeline.extraction.service import SCHEMA
from evidence_pipeline.schemas.pico import SourceDocument
from evidence_pipeline.tests.fixtures import fixture, source
from evidence_pipeline.tests.test_transport import encode


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.dto = fixture()
        self.sources = [SourceDocument.model_validate(source())]

    def test_valid_measurements_remain_identical(self):
        result, excluded = ground_transport(encode(self.dto), SCHEMA, self.sources)
        self.assertEqual(result.model_dump(mode="json"), self.dto)
        self.assertEqual(excluded, [])

    def test_unsupported_estimate_removed_and_audited(self):
        wire = encode(self.dto)
        next(f for f in wire["facts"] if f["raw"] == "0.8")["raw"] = "9.876"
        original = deepcopy(wire)
        result, excluded = ground_transport(wire, SCHEMA, self.sources)
        self.assertIsNone(result.results[0].estimate.value)
        self.assertEqual(result.results[0].p_values[0].value.value, 0.05)
        self.assertTrue(any(e.get("field") == "estimate" for e in excluded))
        self.assertEqual(wire, original)

    def test_empty_shell_rejected(self):
        self.dto["results"] = []
        with self.assertRaisesRegex(PipelineError, "insufficient_source_grounded_pico"):
            ground_transport(encode(self.dto), SCHEMA, self.sources)

    def test_fabricated_passage_cannot_be_accepted(self):
        wire = encode(self.dto)
        for passage in wire["passages"]:
            passage["quote"] = "This is invented source material."
        with self.assertRaises((PipelineError, ValueError)):
            ground_transport(wire, SCHEMA, self.sources)

    def test_repair_feedback_identifies_unsupported_outcome_label(self):
        wire = encode(self.dto)
        next(f for f in wire["facts"] if f["raw"] == "mortality")["raw"] = (
            "invented outcome"
        )
        with self.assertRaises(PipelineError) as raised:
            ground_transport(wire, SCHEMA, self.sources)
        self.assertTrue(
            any(
                issue["loc"][-1] == "name"
                for issue in raised.exception.validation_issues
            )
        )

    def test_unique_quote_locator_is_lossless_and_audited(self):
        wire = encode(self.dto)
        wire["passages"][0]["occurrence"] = 1
        original = deepcopy(wire)
        result, audit = ground_transport(wire, SCHEMA, self.sources)
        self.assertEqual(result.results[0].estimate.value, 0.8)
        self.assertEqual(wire, original)
        self.assertTrue(
            any(a["reason"] == "unique_exact_quote_locator_normalized" for a in audit)
        )
