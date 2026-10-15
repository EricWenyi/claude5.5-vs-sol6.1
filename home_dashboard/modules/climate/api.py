"""JSON API of the 温湿度 tab: latest reading, history, and manual reference checks."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ...server import ApiError
from .collector import STALE_AFTER_S
from .store import Store

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
