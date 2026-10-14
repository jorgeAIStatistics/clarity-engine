"""A database that is away must not stop the evidence API from serving.

On 13 October the Render Postgres instance stopped resolving. production.main() called the PICO
seed import unguarded, psycopg raised OperationalError, the exception escaped main(), and the
service exited 1 on every deploy. The API never touches PostgreSQL — it reads Neo4j and the
published snapshot — so the whole site was down for a dependency it does not use.
"""
import unittest
from unittest import mock

import production


class PostgresReachableTest(unittest.TestCase):
    def test_a_url_that_merely_looks_like_postgres_is_not_a_database(self):
        def refuse(*_a, **_k):
            raise OSError("[Errno -2] Name or service not known")
        self.assertFalse(production.postgres_reachable('postgresql://db/x', connect=refuse))

    def test_a_database_that_answers_is_reachable(self):
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        self.assertTrue(production.postgres_reachable('postgresql://db/x', connect=lambda *a, **k: connection))
        connection.execute.assert_called_once_with('SELECT 1')

    def test_a_missing_or_non_postgres_url_is_simply_not_ready(self):
        for url in ('', None, 'sqlite:///local.db', 'mysql://db'):
            self.assertFalse(production.postgres_reachable(url, connect=lambda *a, **k: None))


class CommandsTest(unittest.TestCase):
    def workers(self, env, **kw):
        return [c for c in production.commands(env, **kw) if not any('evidence.warm' in p for p in c)]

    def test_the_api_starts_even_though_the_database_did_not_answer(self):
        started = self.workers({'DATABASE_URL': 'postgresql://db'}, database_ready=False)
        self.assertEqual(len(started), 1, 'the API is the only child that does not need PostgreSQL')
        self.assertIn('gunicorn', started[0])

    def test_a_child_that_needs_the_database_is_not_started_without_one(self):
        # Starting it anyway means it exits at once, and the supervisor treats any child exiting
        # as fatal — so an unreachable database would restart-loop the whole service.
        for command in self.workers({'DATABASE_URL': 'postgresql://db'}, database_ready=False):
            self.assertNotIn('living_research', ' '.join(command))
            self.assertNotIn('evidence_pipeline.worker', ' '.join(command))

    def test_a_reachable_database_still_starts_the_pipeline(self):
        started = self.workers({'DATABASE_URL': 'postgresql://db'}, database_ready=True)
        self.assertEqual(len(started), 2)
        self.assertIn('living_research', ' '.join(started[1]))

    def test_the_pico_worker_waits_for_its_database_rather_than_failing_the_deploy(self):
        env = {'DATABASE_URL': 'postgresql://db', 'CLARITY_PICO_ENABLED': '1', 'CLARITY_RESEARCH_ENABLED': '0'}
        started = self.workers(env, database_ready=False)
        self.assertEqual(len(started), 1)
        # A URL that is not PostgreSQL at all is a misconfiguration and stays loud.
        with self.assertRaises(RuntimeError):
            production.commands({'CLARITY_PICO_ENABLED': '1'}, database_ready=False)

    def test_the_warmer_never_needed_a_database(self):
        self.assertTrue(any('evidence.warm' in p for c in production.commands({}, database_ready=False) for p in c))

    def test_callers_that_pass_no_readiness_keep_the_old_behaviour(self):
        self.assertEqual(len(self.workers({})), 1)
        self.assertEqual(len(self.workers({'DATABASE_URL': 'postgresql://db'})), 2)


if __name__ == '__main__':
    unittest.main()
