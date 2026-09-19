"""The warmer must never take the service down with it, and must never be mistaken for a fix
for platform spin-down."""
import unittest
from unittest.mock import patch

import production
from evidence import warm


class WarmTests(unittest.TestCase):
    def test_it_is_a_supervised_child_and_can_be_turned_off(self):
        started = production.commands({'PORT': '8000'})
        self.assertTrue(any('evidence.warm' in part for command in started for part in command))
        self.assertFalse(any('evidence.warm' in part for command in production.commands({'PORT': '8000', 'CLARITY_WARM_ENABLED': '0'}) for part in command))

    def test_it_pings_the_paths_that_are_actually_cold(self):
        """Health alone proves the process is up; it does not warm Neo4j or the catalog cache."""
        self.assertEqual(warm.PATHS, ('/api/health', '/api/evidence/graph/stats', '/api/library'))

    def test_a_refused_connection_is_recorded_rather_than_raised(self):
        # The warmer's own failure must never surface as a crash: production.py treats a child that
        # exits as a service failure and restarts gunicorn with it.
        status, elapsed = warm.ping('http://127.0.0.1:1', '/api/health', timeout=2)
        self.assertIsInstance(status, str, 'a connection error is reported, not raised')
        self.assertIsInstance(elapsed, int)

    def test_a_sweep_reports_every_path_even_when_one_fails(self):
        with patch.object(warm, 'ping', side_effect=[(200, 5), ('URLError', 12), (503, 30)]):
            results = warm.sweep('http://127.0.0.1:8000')
        self.assertEqual(sorted(results), sorted(warm.PATHS))
        self.assertEqual(results['/api/library'], (503, 30))

    def test_the_interval_cannot_be_set_to_a_hammer(self):
        self.assertGreaterEqual(warm.INTERVAL, 60)

    def test_a_sweep_survives_a_503_and_reports_it_as_unhealthy(self):
        """A restarting API answering 503 is the ordinary case this exists for, not a reason to stop."""
        with patch.object(warm, 'ping', return_value=(503, 8)):
            self.assertFalse(warm.run_once('http://127.0.0.1:8000'))
        # And the next sweep runs normally: nothing latched, nothing raised.
        with patch.object(warm, 'ping', return_value=(200, 12)):
            self.assertTrue(warm.run_once('http://127.0.0.1:8000'))

    def test_a_sweep_that_blows_up_is_reported_and_not_raised(self):
        with patch.object(warm, 'sweep', side_effect=RuntimeError('socket exploded')):
            self.assertFalse(warm.run_once('http://127.0.0.1:8000'))
        with patch.object(warm, 'ping', return_value=(200, 5)):
            self.assertTrue(warm.run_once('http://127.0.0.1:8000'), 'the warmer must resume after a failure')

    def test_a_connection_error_counts_as_unhealthy_rather_than_healthy(self):
        """ping returns a string for a transport error; that must never read as a status under 400."""
        with patch.object(warm, 'ping', return_value=('URLError', 20)):
            self.assertFalse(warm.run_once('http://127.0.0.1:8000'))

if __name__ == '__main__':
    unittest.main()
