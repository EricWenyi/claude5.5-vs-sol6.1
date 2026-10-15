import json
import math
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from etekcity_esf551_ble import IMPEDANCE_KEY, WEIGHT_KEY, ScaleData

from home_dashboard.modules.weight import WeightModule
from home_dashboard.modules.weight.api import Profile, WeightApi
from home_dashboard.modules.weight.collector import ScaleCollector
from home_dashboard.modules.weight.store import WeightStore
from home_dashboard.server import ApiError, make_server

DAY = 86400
T = 1_800_000_000  # "now" in these tests
ME = Profile(height_cm=175, age=45, sex="male")  # made-up person


def weigh_ins(store, rows):
    """rows: (days before T, kg, impedance)"""
    return [store.add(T - days * DAY, kg, imp) for days, kg, imp in rows]


class WeightApiTest(unittest.TestCase):
    def setUp(self):
        self.store = WeightStore(":memory:")
        self.ids = weigh_ins(self.store, [
            (35, 73.1, 506), (30, 72.7, 505),   # a month ago: 7-day average 72.9
            (8, 71.5, 503), (7, 71.1, 502),     # a week ago: 7-day average 71.3
            (2, 70.7, 501), (1, 70.5, 499), (0, 70.4, 500),  # now: 7-day average 211.6 / 3 = 70.5333
        ])
        self.api = WeightApi(self.store, ME)

    def test_waiting_before_first_weigh_in(self):
        self.assertEqual(WeightApi(WeightStore(":memory:"), ME).latest(now=T), {"status": "waiting"})

    def test_latest_with_body_metrics(self):
        latest = self.api.latest(now=T)
        self.assertEqual((latest["status"], latest["ts"], latest["weight_kg"], latest["impedance"]),
                         ("ok", T, 70.4, 500))
        # 70.4 / 1.75² = 22.988 -> 22.98; 0.103·45 + 1.524·22.98 − 500/500 − 22 = 16.657 -> 16.6
        self.assertEqual(latest["metrics"]["body_mass_index"], 22.98)
        self.assertEqual(latest["metrics"]["body_fat_percentage"], 16.6)

    def test_body_fat_offset_carries_into_derived_metrics(self):
        # E.g. calibrated against a DEXA scan that read 10 points higher than the scale.
        api = WeightApi(self.store, Profile(height_cm=175, age=45, sex="male", body_fat_offset=10.0))
        latest = api.latest(now=T)
        self.assertEqual(latest["body_fat_offset"], 10.0)
        self.assertEqual(latest["metrics"]["body_fat_percentage"], 26.6)  # 16.6 + 10
        self.assertEqual(latest["metrics"]["fat_free_weight"], 51.67)     # 70.4 × (1 − 0.266)
        self.assertEqual(api.history(1, now=T)["points"][-1][3], 26.6)

    def test_change_compares_seven_day_averages(self):
        change = self.api.latest(now=T)["change"]
        self.assertEqual(change, {"week": -0.77, "month": -2.37})  # 70.5333 − 71.3, 70.5333 − 72.9

    def test_change_needs_data_in_both_windows(self):
        store = WeightStore(":memory:")
        weigh_ins(store, [(1, 70.5, 499), (0, 70.4, 500)])
        self.assertEqual(WeightApi(store, ME).latest(now=T)["change"], {"week": None, "month": None})

    def test_metrics_without_profile_or_impedance(self):
        self.assertIsNone(WeightApi(self.store, Profile()).latest(now=T)["metrics"])
        store = WeightStore(":memory:")
        weigh_ins(store, [(0, 70.4, None)])  # stepped on with socks: no impedance
        self.assertEqual(WeightApi(store, ME).latest(now=T)["metrics"], {"body_mass_index": 22.98})

    def test_history_points_and_trailing_average(self):
        h = self.api.history(10, now=T)
        self.assertEqual([p[0] for p in h["points"]], self.ids[2:])
        by_ts = {p[1]: p for p in h["points"]}
        # point: [id, ts, kg, body fat %, 7-day average up to that point]
        self.assertEqual(by_ts[T - DAY][2], 70.5)
        # (71.1 + 70.7 + 70.5) / 3; the 71.5 from exactly 7 days before that point is out
        self.assertEqual(by_ts[T - DAY][4], 70.77)
        self.assertEqual(by_ts[T][3], 16.6)

    def test_history_rejects_bad_days(self):
        for days in (0, -1, math.nan, math.inf, 4000):
            with self.assertRaises(ApiError, msg=days):
                self.api.history(days, now=T)

    def test_delete(self):
        self.assertEqual(self.api.delete(self.ids[-1]), {"deleted": self.ids[-1]})
        self.assertEqual(self.api.latest(now=T)["weight_kg"], 70.5)
        with self.assertRaises(ApiError):
            self.api.delete(self.ids[-1])


def scale_data(kg=None, impedance=None):
    data = ScaleData(name="Etekcity Smart Fitness Scale", address="AA:BB:CC:DD:EE:FF")
    if kg is not None:
        data.measurements[WEIGHT_KEY] = kg
    if impedance is not None:
        data.measurements[IMPEDANCE_KEY] = impedance
    return data


class ScaleCollectorTest(unittest.TestCase):
    def setUp(self):
        self.store = WeightStore(":memory:")
        self.now = [T]
        self.c = ScaleCollector(self.store, "AA:BB:CC:DD:EE:FF", clock=lambda: self.now[0])

    def rows(self):
        return [(w.ts, w.weight_kg, w.impedance) for w in self.store.since(0)]

    def test_stores_each_weigh_in(self):
        self.c.on_reading(scale_data(70.4, 500))
        self.now[0] += 3600
        self.c.on_reading(scale_data(70.2))
        self.assertEqual(self.rows(), [(T, 70.4, 500), (T + 3600, 70.2, None)])

    def test_same_reading_right_after_is_not_stored_twice(self):
        self.c.on_reading(scale_data(70.4, 500))
        self.now[0] += 90  # e.g. the scale reconnects and resends its final frame
        self.c.on_reading(scale_data(70.4, 500))
        self.now[0] += 121
        self.c.on_reading(scale_data(70.4, 500))
        self.assertEqual(len(self.rows()), 2)

    def test_reading_without_weight_is_ignored(self):
        self.c.on_reading(scale_data(impedance=500))
        self.assertEqual(self.rows(), [])


class WeightHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = WeightStore(":memory:")
        api = WeightApi(cls.store, ME)
        cls.server = make_server([WeightModule(api, collector=None)], "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, method="GET"):
        try:
            with urlopen(Request(self.base + path, method=method)) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_routes(self):
        import time
        reading_id = self.store.add(time.time(), 70.4, 500)
        status, latest = self.request("/api/weight/latest")
        self.assertEqual((status, latest["weight_kg"]), (200, 70.4))
        status, history = self.request("/api/weight/history?days=30")
        self.assertEqual((status, len(history["points"])), (200, 1))
        self.assertEqual(self.request("/api/weight/history?days=x")[0], 400)
        self.assertEqual(self.request(f"/api/weight/readings/{reading_id}", "DELETE")[0], 200)
        self.assertEqual(self.request(f"/api/weight/readings/{reading_id}", "DELETE")[0], 404)
        self.assertEqual(self.request("/api/home")[1], {"tabs": [{"id": "weight", "title": "体重"}]})


if __name__ == "__main__":
    unittest.main()
