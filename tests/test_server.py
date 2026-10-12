import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bedroom_climate.server import Api, ApiError, Settings, make_server
from bedroom_climate.store import Sample, Store


class FakeCollector:
    def __init__(self, latest=None):
        self.latest = latest


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        now = int(time.time())
        # Three hours of readings, one per minute, with a 30-minute outage in the middle.
        self.store.add_readings(
            [Sample(ts, "GVH5075_TEST", 20.0 + (ts - now) / 36000, 45.0) for ts in range(now - 3 * 3600, now, 60)
             if not now - 7200 <= ts < now - 5400]
        )
        self.collector = FakeCollector(Sample(time.time(), "GVH5075_TEST", 21.0, 44.0, 90, -60))
        self.api = Api(self.store, self.collector, Settings(temp_offset=-0.4, humidity_offset=2.0))

    def test_latest_applies_offsets(self):
        latest = self.api.latest()
        self.assertEqual(latest["status"], "ok")
        self.assertEqual((latest["temp_c"], latest["humidity"]), (20.6, 46.0))

    def test_latest_waiting_and_stale(self):
        self.collector.latest = None
        self.assertEqual(self.api.latest()["status"], "waiting")
        self.collector.latest = Sample(time.time() - 3600, "GVH5075_TEST", 21.0, 44.0)
        self.assertEqual(self.api.latest()["status"], "stale")

    def test_humidity_offset_is_clamped(self):
        api = Api(self.store, self.collector, Settings(humidity_offset=60))
        self.assertEqual(api.latest()["humidity"], 100.0)

    def test_history_buckets_and_stats(self):
        h = self.api.history(6)
        self.assertEqual(h["bucket"], 60)
        self.assertEqual(len(h["points"]), 3 * 60 - 30)
        self.assertTrue(all(p[2] == 47.0 for p in h["points"]))
        self.assertAlmostEqual(h["stats"]["temp_c"]["max"], 20.0 - 60 / 36000 - 0.4, places=2)

        week = self.api.history(24 * 7)
        self.assertEqual(week["bucket"], 1560)  # 7 days / 400 points, rounded up to whole minutes
        self.assertLess(len(week["points"]), 400)

    def test_history_rejects_bad_hours(self):
        for hours in (0, -1, float("nan"), float("inf"), 24 * 365):
            with self.assertRaises(ApiError, msg=hours):
                self.api.history(hours)

    def test_reference_checks(self):
        self.api.add_check({"temp_c": 21.0, "humidity": 50})
        self.api.add_check({"temp_c": "20.4", "humidity": "48"})
        result = self.api.checks()
        # Sensor 21.0 °C / 44 % raw -> 20.6 / 46.0 after offsets.
        diffs = sorted((c["diff_temp_c"], c["diff_humidity"]) for c in result["checks"])
        self.assertEqual(diffs, [(-0.4, -4.0), (0.2, -2.0)])
        self.assertEqual(result["summary"], {"n": 2, "mean_diff_temp_c": -0.1, "mean_diff_humidity": -3.0})

    def test_check_needs_fresh_sensor_reading(self):
        self.collector.latest = Sample(time.time() - 600, "GVH5075_TEST", 21.0, 44.0)
        with self.assertRaises(ApiError):
            self.api.add_check({"temp_c": 21.0, "humidity": 50})


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store = Store(":memory:")
        collector = FakeCollector(Sample(time.time(), "GVH5075_TEST", 21.0, 44.0, 90, -60))
        cls.server = make_server(Api(store, collector, Settings()), "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req) as res:
                return res.status, res.read()
        except HTTPError as e:
            return e.code, e.read()

    def test_dashboard_page(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("卧室温湿度".encode(), body)

    def test_check_roundtrip(self):
        status, body = self.request("/api/checks", "POST", {"temp_c": 21.2, "humidity": 46})
        self.assertEqual(status, 200)
        check_id = json.loads(body)["id"]
        self.assertEqual(self.request(f"/api/checks/{check_id}", "DELETE")[0], 200)
        self.assertEqual(self.request(f"/api/checks/{check_id}", "DELETE")[0], 404)

    def test_bad_input(self):
        self.assertEqual(self.request("/api/checks", "POST", {"temp_c": "warm"})[0], 400)
        self.assertEqual(self.request("/api/checks", "POST", [1, 2])[0], 400)
        self.assertEqual(self.request("/api/history?hours=abc")[0], 400)
        self.assertEqual(self.request("/api/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
