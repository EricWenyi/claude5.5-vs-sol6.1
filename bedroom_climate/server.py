"""Tiny HTTP server: the dashboard page plus a JSON API."""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .collector import STALE_AFTER_S
from .store import Store

log = logging.getLogger(__name__)

INDEX_HTML = Path(__file__).parent / "static" / "index.html"

# Two healthy units should agree within the sum of their rated accuracies:
# Govee H5075 ±0.3 °C / ±3 %RH, AcuRite 01083M ±0.2 °C (±0.5 °F) / ±2 %RH.
AGREEMENT_TEMP_C = 0.5
AGREEMENT_HUMIDITY = 5.0

# A manual check is only paired with a sensor reading this fresh.
CHECK_MAX_AGE_S = 180

MAX_HISTORY_HOURS = 24 * 90
HISTORY_POINTS = 400


@dataclass
class Settings:
    temp_offset: float = 0.0
    humidity_offset: float = 0.0
    temp_range_c: tuple[float, float] = (15.56, 19.44)  # 60-67 °F
    humidity_range: tuple[float, float] = (30.0, 50.0)
    demo: bool = False

    def temp(self, raw: float) -> float:
        return round(raw + self.temp_offset, 2)

    def humidity(self, raw: float) -> float:
        return round(min(100.0, max(0.0, raw + self.humidity_offset)), 2)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, store: Store, collector, settings: Settings):
        self.store = store
        self.collector = collector
        self.settings = settings

    def config(self) -> dict:
        s = self.settings
        return {
            "demo": s.demo,
            "temp_range_c": s.temp_range_c,
            "humidity_range": s.humidity_range,
            "offsets": {"temp_c": s.temp_offset, "humidity": s.humidity_offset},
            "agreement": {"temp_c": AGREEMENT_TEMP_C, "humidity": AGREEMENT_HUMIDITY},
        }

    def latest(self) -> dict:
        s = self.collector.latest
        if s is None:
            return {"status": "waiting"}
        age = time.time() - s.ts
        return {
            "status": "stale" if age > STALE_AFTER_S else "ok",
            "ts": s.ts,
            "age_s": round(age),
            "device": s.device,
            "temp_c": self.settings.temp(s.temp_c),
            "humidity": self.settings.humidity(s.humidity),
            "battery": s.battery,
            "rssi": s.rssi,
        }

    def history(self, hours: float) -> dict:
        if not 0 < hours <= MAX_HISTORY_HOURS:
            raise ApiError(400, f"hours 需在 0 到 {MAX_HISTORY_HOURS} 之间")
        since = int(time.time() - hours * 3600)
        # Whole minutes, sized so the chart gets about HISTORY_POINTS points.
        bucket = max(60, math.ceil(hours * 3600 / HISTORY_POINTS / 60) * 60)
        t, h = self.settings.temp, self.settings.humidity
        stats = self.store.stats(since)
        if stats:
            stats = {
                "temp_c": {k: t(v) for k, v in stats["temp_c"].items()},
                "humidity": {k: h(v) for k, v in stats["humidity"].items()},
            }
        return {
            "since": since,
            "bucket": bucket,
            "points": [[ts, t(temp), h(hum)] for ts, temp, hum in self.store.history(since, bucket)],
            "stats": stats,
        }

    def checks(self) -> dict:
        t, h = self.settings.temp, self.settings.humidity
        rows = []
        for c in self.store.checks():
            sensor_t, sensor_h = t(c["sensor_temp_c"]), h(c["sensor_humidity"])
            rows.append(
                {
                    "id": c["id"],
                    "ts": c["ts"],
                    "ref_temp_c": c["ref_temp_c"],
                    "ref_humidity": c["ref_humidity"],
                    "sensor_temp_c": sensor_t,
                    "sensor_humidity": sensor_h,
                    "diff_temp_c": round(sensor_t - c["ref_temp_c"], 2),
                    "diff_humidity": round(sensor_h - c["ref_humidity"], 2),
                }
            )
        summary = None
        if rows:
            summary = {
                "n": len(rows),
                "mean_diff_temp_c": round(sum(r["diff_temp_c"] for r in rows) / len(rows), 2),
                "mean_diff_humidity": round(sum(r["diff_humidity"] for r in rows) / len(rows), 2),
            }
        return {"checks": rows, "summary": summary}

    def add_check(self, body: dict) -> dict:
        try:
            ref_t = float(body["temp_c"])
            ref_h = float(body["humidity"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "需要填写温度和湿度两个数字") from None
        if not (-40 <= ref_t <= 100 and 0 <= ref_h <= 100):
            raise ApiError(400, "读数超出合理范围")
        s = self.collector.latest
        if s is None or time.time() - s.ts > CHECK_MAX_AGE_S:
            raise ApiError(409, "暂时没有 Govee 的最新读数，无法配对，请稍后再试")
        check_id = self.store.add_check(time.time(), ref_t, ref_h, s)
        return {"id": check_id}

    def delete_check(self, check_id: int) -> dict:
        if not self.store.delete_check(check_id):
            raise ApiError(404, "没有这条记录")
        return {"deleted": check_id}


def make_server(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
                return
            routes = {
                "/api/config": api.config,
                "/api/latest": api.latest,
                "/api/checks": api.checks,
                "/api/history": lambda: api.history(_float_param(url.query, "hours", 24)),
            }
            self._dispatch(routes.get(url.path))

        def do_POST(self):
            if urlparse(self.path).path != "/api/checks":
                self._dispatch(None)
                return
            self._dispatch(lambda: api.add_check(self._json_body()))

        def do_DELETE(self):
            m = re.fullmatch(r"/api/checks/(\d+)", urlparse(self.path).path)
            self._dispatch(m and (lambda: api.delete_check(int(m.group(1)))))

        def _dispatch(self, handler):
            if handler is None:
                self._json(404, {"error": "not found"})
                return
            try:
                self._json(200, handler())
            except ApiError as e:
                self._json(e.status, {"error": str(e)})

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 10_000:
                raise ApiError(400, "请求体为空或过大")
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                raise ApiError(400, "请求体不是合法 JSON") from None
            if not isinstance(body, dict):
                raise ApiError(400, "请求体需是 JSON 对象")
            return body

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), Handler)


def _float_param(query: str, name: str, default: float) -> float:
    values = parse_qs(query).get(name)
    if not values:
        return default
    try:
        return float(values[0])
    except ValueError:
        raise ApiError(400, f"{name} 需是数字") from None
