"""Opt-in, write-bearing integration test for a disposable Neo4j database only."""

import os
import unittest
from uuid import uuid4
from evidence_pipeline.config import Settings
from evidence_pipeline.graph.ingestion import Neo4jIngestor
from evidence_pipeline.tests.test_modules import envelope


@unittest.skipUnless(
    os.getenv("PICO_ALLOW_TEST_WRITES") == "1"
    and os.getenv("PICO_NEO4J_TEST_DATABASE"),
    "Dedicated Neo4j test database not configured",
)
class LiveGraphTests(unittest.TestCase):
    def test_transaction_replay_preserves_result_count(self):
        settings = Settings.from_env()
        driver = settings.graph()
        database = os.environ["PICO_NEO4J_TEST_DATABASE"]
        try:
            driver.verify_connectivity()
            sink = Neo4jIngestor(driver, database)
            sink.initialize()
            env = envelope()
            env.prompt_version = "integration:" + str(uuid4())
            first = sink.ingest(env)
            second = sink.ingest(env)
            self.assertEqual(first, second)
            with driver.session(database=database) as session:
                row = session.run(
                    "MATCH (x:Extraction {id:$id})-[:HAS_RESULT]->(r) RETURN count(r) AS count",
                    id=first["extraction_id"],
                ).single()
                self.assertEqual(row["count"], 1)
        finally:
            driver.close()
