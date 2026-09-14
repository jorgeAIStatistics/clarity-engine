import unittest
from evidence_pipeline.extraction.core import (
    CoreExtraction,
    Comparison,
    LiteralFact,
    expand,
)
from evidence_pipeline.tests.test_modules import envelope
from evidence_pipeline.schemas.pico import PICOExtraction
from evidence_pipeline.common import PipelineError


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.source = envelope().sources[0]

        def fact(raw):
            return LiteralFact(
                raw=raw,
                quote=self.source.text if raw else None,
                confidence=0.9 if raw else None,
            )

        missing = fact(None)
        self.comparison = Comparison(
            population=fact("Adults"),
            n_analyzed=missing,
            intervention=fact("Drug A"),
            comparator=fact("placebo"),
            dose=missing,
            dose_unit=missing,
            outcome=fact("mortality"),
            metric="hazard_ratio",
            metric_quote=self.source.text,
            estimate=fact("0.8"),
            unit=missing,
            confidence_lower=fact("0.6"),
            confidence_upper=fact("1.1"),
            confidence_level_percent=fact("95"),
            p_value=fact("0.05"),
            p_operator="lt",
            contrast=fact("Drug A versus placebo"),
        )
        self.core = CoreExtraction(
            study_design="rct_parallel",
            design_quote=self.source.text,
            comparisons=[self.comparison],
        )

    def test_direct_observations_expand_to_approved_contract(self):
        result = PICOExtraction.model_validate(expand(self.core, self.source))
        self.assertEqual(result.results[0].estimate.value, 0.8)
        self.assertEqual(result.results[0].intervals[0].upper.value, 1.1)
        self.assertEqual(result.populations[0].demographics, [])
        self.assertEqual(result.populations[0].species.missing_reason, "ambiguous")

    def test_fabricated_value_is_rejected(self):
        self.comparison.estimate.raw = "0.71"
        with self.assertRaises(PipelineError):
            expand(self.core, self.source)

    def test_missing_interval_endpoint_is_never_invented(self):
        self.comparison.confidence_upper = LiteralFact(
            raw=None, quote=None, confidence=None
        )
        result = PICOExtraction.model_validate(expand(self.core, self.source))
        self.assertIsNone(result.results[0].intervals[0].upper.value)

class SpanTests(CoreTests):
    def token_payload(self):
        from evidence_pipeline.extraction.core import source_tokens
        tokens = source_tokens(self.source.text)
        def selection(raw):
            if raw is None:
                return dict(first_token=None, last_token=None, confidence=None)
            start = self.source.text.index(raw)
            return dict(first_token=next(i for i,t in enumerate(tokens) if t[0]==start),
                        last_token=next(i for i,t in enumerate(tokens) if t[1]==start+len(raw)),confidence=.9)
        values = self.comparison.model_dump()
        for key, value in list(values.items()):
            if isinstance(value, dict): values[key]=selection(value['raw'])
            elif key == 'metric_quote': values[key]=selection(self.source.text)
        return dict(study_design='rct_parallel',design_quote=selection(self.source.text),comparisons=[values])

    def test_selected_bytes_and_invalid_observation_quarantine(self):
        from copy import deepcopy
        from evidence_pipeline.extraction.core import SpanProvider
        provider = object.__new__(SpanProvider)
        raw=self.token_payload()
        bad=deepcopy(raw['comparisons'][0])
        bad['estimate']['last_token']=999999
        raw['comparisons'].append(bad)
        result=PICOExtraction.model_validate(provider.decode_payload(raw,[self.source]))
        self.assertEqual(len(result.results),1)
        self.assertEqual(result.results[0].estimate.raw,'0.8')
        self.assertEqual(provider.decode_audit,[{'observation':1,'reason':'span_token_bounds_invalid'}])

    def test_all_invalid_observations_reject_document(self):
        from evidence_pipeline.extraction.core import SpanProvider
        raw=self.token_payload()
        raw['comparisons'][0]['population']['first_token']=999999
        with self.assertRaisesRegex(PipelineError,'no_valid_source_bound_observations'):
            object.__new__(SpanProvider).decode_payload(raw,[self.source])
