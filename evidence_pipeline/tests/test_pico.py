import unittest
from copy import deepcopy
from pydantic import ValidationError
from evidence_pipeline.schemas.pico import (
    PICOExtraction,
    SourceDocument,
    validate_sources,
)
from evidence_pipeline.tests.fixtures import fixture, source


class SchemaTests(unittest.TestCase):
    def test_valid_fixture_and_json_roundtrip(self):
        result = PICOExtraction.model_validate(fixture())
        validate_sources(result, [SourceDocument.model_validate(source())])
        self.assertEqual(
            result, PICOExtraction.model_validate_json(result.model_dump_json())
        )

    def test_all_object_keys_required_and_extra_keys_forbidden(self):
        schema = PICOExtraction.model_json_schema()

        def walk(x):
            if isinstance(x, dict):
                if x.get("type") == "object":
                    self.assertIs(x.get("additionalProperties"), False)
                    self.assertEqual(set(x["properties"]), set(x["required"]))
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(schema)

    def test_extra_prose_rejected(self):
        x = fixture()
        x["summary"] = "It works"
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_strict_numbers(self):
        for value in ("0.8", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                x = fixture()
                x["results"][0]["estimate"]["value"] = value
                with self.assertRaises(ValidationError):
                    PICOExtraction.model_validate(x)

    def test_missing_ci_level_stays_missing(self):
        x = fixture()
        x["results"][0]["intervals"][0]["level_percent"] = {
            "value": None,
            "raw": None,
            "missing_reason": "not_reported",
            "evidence": [],
            "extraction_confidence": None,
        }
        self.assertIsNone(
            PICOExtraction.model_validate(x).results[0].intervals[0].level_percent.value
        )

    def test_inequality_is_retained(self):
        self.assertEqual(
            PICOExtraction.model_validate(fixture()).results[0].p_values[0].comparator,
            "lt",
        )

    def test_reversed_interval_rejected(self):
        x = fixture()
        i = x["results"][0]["intervals"][0]
        i["lower"], i["upper"] = i["upper"], i["lower"]
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_unknown_ids_and_duplicate_ids(self):
        x = fixture()
        x["results"][0]["outcome_id"] = "missing"
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)
        x = fixture()
        x["arms"].append(deepcopy(x["arms"][0]))
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_protocol_cannot_publish_results(self):
        x = fixture()
        x["document_kind"] = "protocol"
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_changed_source_rejected(self):
        x = source()
        x["text"] += " changed"
        with self.assertRaises(ValidationError):
            SourceDocument.model_validate(x)

    def test_unsupported_source_id_rejected(self):
        with self.assertRaises(ValueError):
            validate_sources(PICOExtraction.model_validate(fixture()), [])

    def test_extracted_number_must_match_literal_token(self):
        x = fixture()
        x["results"][0]["estimate"]["value"] = 0.9
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_null_cannot_hide_missingness(self):
        x = fixture()
        x["results"][0]["estimate"]["value"] = None
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)

    def test_population_cycle_rejected(self):
        x = fixture()
        x["populations"][0]["parent_population_id"] = "p1"
        with self.assertRaises(ValidationError):
            PICOExtraction.model_validate(x)


if __name__ == "__main__":
    unittest.main()
