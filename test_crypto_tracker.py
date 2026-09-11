"""
Tests for crypto_tracker.py — offline fallback, threshold
classification, and the "log only transitions" check-cycle logic.
"""

import sys
import types
import unittest

import crypto_tracker as ct


class FakeRequestException(Exception):
    pass


def install_fake_requests(get_fn):
    """Dual-patch: inject a fake `requests` module into sys.modules AND
    reassign crypto_tracker's already-bound `requests` name, since a
    sys.modules swap alone doesn't affect a name already bound by
    `import requests` at module load time."""
    fake_requests = types.ModuleType("requests")
    fake_requests.get = get_fn
    fake_requests.RequestException = FakeRequestException
    sys.modules["requests"] = fake_requests
    ct.requests = fake_requests
    return fake_requests


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeRequestException(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestOfflineFallback(unittest.TestCase):
    def setUp(self):
        self._real_requests = ct.requests

    def tearDown(self):
        ct.requests = self._real_requests
        sys.modules["requests"] = self._real_requests

    def test_connection_failure_falls_back_to_offline_sample(self):
        def broken_get(*args, **kwargs):
            raise FakeRequestException("connection refused")

        install_fake_requests(broken_get)

        prices, source = ct.get_prices(["bitcoin", "ethereum"])
        self.assertEqual(source, "offline sample")
        self.assertIn("bitcoin", prices)
        self.assertIn("ethereum", prices)

    def test_offline_sample_omits_unknown_coin_ids(self):
        def broken_get(*args, **kwargs):
            raise FakeRequestException("connection refused")

        install_fake_requests(broken_get)

        prices, source = ct.get_prices(["bitcoin", "not-a-real-coin"])
        self.assertIn("bitcoin", prices)
        self.assertNotIn("not-a-real-coin", prices)


class TestLivePath(unittest.TestCase):
    def setUp(self):
        self._real_requests = ct.requests

    def tearDown(self):
        ct.requests = self._real_requests
        sys.modules["requests"] = self._real_requests

    def test_live_fetch_is_used_when_available(self):
        def fake_get(url, params=None, timeout=5):
            self.assertIn("bitcoin", params["ids"])
            return FakeResponse({"bitcoin": {"usd": 71000.5}})

        install_fake_requests(fake_get)

        prices, source = ct.get_prices(["bitcoin"])
        self.assertEqual(source, "live")
        self.assertEqual(prices["bitcoin"], 71000.5)

    def test_falls_back_when_live_response_has_no_usable_data(self):
        def fake_get(url, params=None, timeout=5):
            return FakeResponse({})  # coin id not recognized by the API

        install_fake_requests(fake_get)

        prices, source = ct.get_prices(["bitcoin"])
        self.assertEqual(source, "offline sample")


class TestClassifyStatus(unittest.TestCase):
    def test_above_threshold(self):
        self.assertEqual(ct.classify_status(75000, alert_above=70000), "above")

    def test_below_threshold(self):
        self.assertEqual(ct.classify_status(50000, alert_below=55000), "below")

    def test_within_range(self):
        self.assertEqual(ct.classify_status(60000, alert_above=70000, alert_below=55000), "within")

    def test_no_thresholds_configured_is_always_within(self):
        self.assertEqual(ct.classify_status(999999), "within")

    def test_exactly_at_threshold_counts_as_crossed(self):
        self.assertEqual(ct.classify_status(70000, alert_above=70000), "above")


class TestRunCheckCycle(unittest.TestCase):
    def setUp(self):
        self._real_requests = ct.requests
        watchlist_payload = {"bitcoin": {"usd": 75000.0}}

        def fake_get(url, params=None, timeout=5):
            return FakeResponse(watchlist_payload)

        install_fake_requests(fake_get)
        self.watchlist = [{"id": "bitcoin", "symbol": "BTC", "alert_above": 70000, "alert_below": 40000}]

    def tearDown(self):
        ct.requests = self._real_requests
        sys.modules["requests"] = self._real_requests

    def test_first_time_above_threshold_is_a_transition(self):
        results, transitions, state, source = ct.run_check_cycle(self.watchlist, {})
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["to_status"], "above")
        self.assertEqual(state["bitcoin"], "above")

    def test_staying_above_threshold_across_cycles_does_not_re_alert(self):
        _, _, state, _ = ct.run_check_cycle(self.watchlist, {})
        _, transitions_second, _, _ = ct.run_check_cycle(self.watchlist, state)
        self.assertEqual(transitions_second, [])

    def test_a_coin_within_range_produces_no_transition(self):
        watchlist = [{"id": "bitcoin", "symbol": "BTC", "alert_above": 100000, "alert_below": 1000}]
        _, transitions, state, _ = ct.run_check_cycle(watchlist, {})
        self.assertEqual(transitions, [])
        self.assertEqual(state["bitcoin"], "within")

    def test_price_crossing_down_from_above_produces_a_new_transition(self):
        _, _, state, _ = ct.run_check_cycle(self.watchlist, {})  # now "above"

        def fake_get_lower(url, params=None, timeout=5):
            return FakeResponse({"bitcoin": {"usd": 30000.0}})

        install_fake_requests(fake_get_lower)
        _, transitions, new_state, _ = ct.run_check_cycle(self.watchlist, state)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_status"], "above")
        self.assertEqual(transitions[0]["to_status"], "below")


if __name__ == "__main__":
    unittest.main()
