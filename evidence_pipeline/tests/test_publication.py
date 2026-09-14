import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from flask import Flask
from evidence_pipeline.state import State
from evidence_pipeline.bootstrap import bootstrap
from evidence_pipeline.publication import public_records, visual_rows, target_ids
from evidence_pipeline.public_routes import blueprint
from evidence_pipeline.tests.test_modules import envelope


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.state = State(":memory:")
        self.env = envelope()
        self.record = {"id": "e1", "envelope": self.env.model_dump(mode="json")}
        self.state.put("extraction", "e1", self.record)

    def tearDown(self):
        self.state.close()

    def test_uningested_extraction_cannot_be_published(self):
        self.assertEqual(public_records(self.state), [])

    def test_corrupted_source_with_receipt_is_not_published(self):
        self.record["envelope"]["sources"][0]["text"] += "changed"
        self.state.put("extraction", "e1", self.record)
        self.state.put("graph_receipt", "e1", {"id": "e1"})
        self.assertEqual(public_records(self.state), [])

    def test_public_json_has_sources_but_no_provider_credentials(self):
        self.state.put("graph_receipt", "e1", {"id": "e1"})
        rows = public_records(self.state)
        app = Flask(__name__)
        app.register_blueprint(blueprint)
        with patch(
            "evidence_pipeline.public_routes.current_records", return_value=rows
        ):
            response = app.test_client().get("/api/pico/studies/12345678?download=1")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("sources", response.json)
            self.assertNotIn("envelope", response.json)
            self.assertEqual(
                app.test_client().get("/api/pico/studies/not-a-pmid").status_code, 404
            )

    def test_context_incomplete_record_is_not_a_chart_point(self):
        self.state.put("graph_receipt", "e1", {"id": "e1"})
        item = public_records(self.state)[0]
        item["envelope"].extraction.results[0].reference_arm_id = None
        rows, withheld = visual_rows(item)
        self.assertEqual(rows, [])
        self.assertTrue(withheld)

    def test_search_target_does_not_bind_unrelated_intervention(self):
        self.assertEqual(target_ids(self.env.extraction), [])

    def test_bootstrap_preserves_newer_durable_records(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / "seed.gz"
            database = str(Path(directory) / "state.sqlite3")
            seed.write_bytes(
                gzip.compress(
                    json.dumps(
                        {
                            "version": 1,
                            "records": [
                                {
                                    "kind": "activation",
                                    "id": "daily-worker",
                                    "value": {"enabled": False},
                                }
                            ],
                        }
                    ).encode()
                )
            )
            self.assertEqual(bootstrap(database, seed), 1)
            state = State(database)
            state.put("activation", "daily-worker", {"enabled": True})
            state.close()
            self.assertEqual(bootstrap(database, seed), 0)
            state = State(database)
            self.assertTrue(state.get("activation", "daily-worker")["enabled"])
            state.close()

    def test_postgres_queries_are_namespaced_and_parameterized(self):
        state = object.__new__(State)
        state.pg = True
        state.db = Mock()
        state.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", ("extraction", "e1")
        )
        state.db.execute.assert_called_once_with(
            "SELECT body FROM clarity_pico_records WHERE kind=%s AND id=%s",
            ("extraction", "e1"),
        )
