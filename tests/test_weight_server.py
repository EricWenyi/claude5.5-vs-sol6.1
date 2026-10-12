import datetime as dt
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from weight_tracker.server import Api, ApiError, make_server
from weight_tracker.store import Store

TODAY = dt.date.today().isoformat()


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.api = Api(self.store())

    def store(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        return store

    def test_add_list_delete(self):
        first = self.api.add_entry({"date": TODAY, "time": "07:10", "weight": "165.4", "unit": "lb", "note": " 早上 "})["id"]
        self.api.add_entry({"date": TODAY, "weight": 75, "unit": "kg"})
        entries = self.api.entries()["entries"]
        self.assertEqual([(e["weight"], e["unit"], e["time"]) for e in entries], [(165.4, "lb", "07:10"), (75.0, "kg", None)])
        self.assertEqual(entries[0]["note"], "早上")
        self.assertEqual(self.api.summary()["days"][0]["n"], 2)
        self.api.delete_entry(first)
        with self.assertRaises(ApiError) as cm:
            self.api.delete_entry(first)
        self.assertEqual(cm.exception.status, 404)

    def test_rejects_implausible_entries(self):
        tomorrow2 = (dt.date.today() + dt.timedelta(days=2)).isoformat()
        for body in (
            {"date": TODAY, "weight": 16.5, "unit": "lb"},  # a missing digit
            {"date": TODAY, "weight": 1650, "unit": "lb"},
            {"date": TODAY, "weight": 165, "unit": "stone"},
            {"date": TODAY, "weight": "nan", "unit": "lb"},
            {"date": tomorrow2, "weight": 165, "unit": "lb"},
            {"date": "10/12/2026", "weight": 165, "unit": "lb"},
            {"date": TODAY, "weight": 165, "unit": "lb", "time": "7am"},
            {"date": TODAY, "weight": 165, "unit": "lb", "note": ["x"]},
            {"weight": 165},
        ):
            with self.assertRaises(ApiError, msg=body) as cm:
                self.api.add_entry(body)
            self.assertEqual(cm.exception.status, 400)
        self.assertEqual(self.api.entries()["entries"], [])

    def test_import_skips_duplicates(self):
        csv = f"date,weight\n{TODAY},165.4\n2026-01-02,170\nbad,1\n"
        self.assertEqual(self.api.import_csv(csv, "lb"),
                         {"added": 2, "duplicates": 0, "errors": ["第 4 行：看不懂日期 'bad'"], "error_count": 1})
        again = self.api.import_csv(csv, "lb")
        self.assertEqual((again["added"], again["duplicates"]), (0, 2))
        with self.assertRaises(ApiError):
            self.api.import_csv(csv, "stone")

    def test_export_roundtrip(self):
        self.api.add_entry({"date": TODAY, "time": "07:10", "weight": 165.4, "unit": "lb", "note": "a, b"})
        other = Api(self.store())
        self.assertEqual(other.import_csv(self.api.export_csv(), "kg")["added"], 1)
        self.assertEqual(other.entries()["entries"][0]["note"], "a, b")


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.server = make_server(Api(cls.store), "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.store.close()

    def request(self, path, method="GET", body=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": content_type})
        try:
            with urlopen(req) as res:
                return res.status, res.read(), res.headers
        except HTTPError as e:
            return e.code, e.read(), e.headers

    def test_dashboard_page(self):
        status, body, _ = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("体重趋势".encode(), body)

    def test_entry_roundtrip(self):
        status, body, _ = self.request("/api/entries", "POST", {"date": TODAY, "weight": 165.4, "unit": "lb"})
        self.assertEqual(status, 200)
        entry_id = json.loads(body)["id"]
        self.assertEqual(json.loads(self.request("/api/summary")[1])["latest"]["weight"], 165.4)
        self.assertEqual(self.request(f"/api/entries/{entry_id}", "DELETE")[0], 200)
        self.assertEqual(self.request(f"/api/entries/{entry_id}", "DELETE")[0], 404)

    def test_import_gbk_csv_and_export(self):
        csv = "日期,体重(kg),备注\n2026-01-03,75.5,体检\n".encode("gbk")
        status, body, _ = self.request("/api/import?unit=lb", "POST", raw=csv, content_type="text/csv")
        self.assertEqual((status, json.loads(body)["added"]), (200, 1))
        status, body, headers = self.request("/api/export.csv")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("2026-01-03,,75.5,kg,体检", body.decode("utf-8-sig"))

    def test_bad_input(self):
        self.assertEqual(self.request("/api/entries", "POST", {"date": TODAY, "weight": "heavy"})[0], 400)
        self.assertEqual(self.request("/api/entries", "POST", [1, 2])[0], 400)
        self.assertEqual(self.request("/api/entries", "POST", raw=b"{")[0], 400)
        self.assertEqual(self.request("/api/import", "POST", raw=b"", content_type="text/csv")[0], 400)
        self.assertEqual(self.request("/api/nope")[0], 404)
        self.assertEqual(self.request("/api/entries/abc", "DELETE")[0], 404)


if __name__ == "__main__":
    unittest.main()
