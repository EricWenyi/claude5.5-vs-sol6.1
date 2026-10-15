"""JSON API of the 体重 tab: latest weigh-in with body-composition estimates, history, deletion."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from math import floor

from etekcity_esf551_ble import BodyMetrics, Sex

from ...server import ApiError
from .store import WeighIn, WeightStore

DAY = 86400
# Weight swings by a kilo or so from day to day; trends are read from 7-day averages.
AVERAGE_S = 7 * DAY
MAX_HISTORY_DAYS = 3650


@dataclass
class Profile:
    """Who stands on the scale. Body fat and the other estimates need all three."""

    height_cm: float | None = None
    age: int | None = None
    sex: str | None = None  # "male" or "female"

    @property
    def complete(self) -> bool:
        return bool(self.height_cm) and self.age is not None and self.sex in ("male", "female")


class WeightApi:
    def __init__(self, store: WeightStore, profile: Profile):
        self.store = store
        self.profile = profile

    def metrics(self, w: WeighIn) -> dict | None:
        """Body-composition estimates for one weigh-in, as the VeSync app computes them for the ESF-551."""
        p = self.profile
        if not p.height_cm:
            return None
        if not (p.complete and w.impedance):
            return {"body_mass_index": floor(w.weight_kg / (p.height_cm / 100) ** 2 * 100) / 100}
        sex = Sex.Male if p.sex == "male" else Sex.Female
        return BodyMetrics(w.weight_kg, p.height_cm / 100, p.age, sex, w.impedance).as_dict()

    def latest(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        w = self.store.latest()
        if w is None:
            return {"status": "waiting"}
        recent = self.store.since(now - 30 * DAY - AVERAGE_S)
        current = _average(recent, now)

        def change(days: int) -> float | None:
            before = _average(recent, now - days * DAY)
            return None if current is None or before is None else round(current - before, 2)

        return {
            "status": "ok",
            "id": w.id,
            "ts": w.ts,
            "weight_kg": w.weight_kg,
            "impedance": w.impedance,
            "metrics": self.metrics(w),
            "change": {"week": change(7), "month": change(30)},
        }

    def history(self, days: float, now: float | None = None) -> dict:
        if not 0 < days <= MAX_HISTORY_DAYS:
            raise ApiError(400, f"days 需在 0 到 {MAX_HISTORY_DAYS} 之间")
        now = time.time() if now is None else now
        since = now - days * DAY
        points = []
        window: deque[WeighIn] = deque()
        total = 0.0
        # Readings from the week before `since` only feed the first points' averages.
        for w in self.store.since(since - AVERAGE_S):
            window.append(w)
            total += w.weight_kg
            while window[0].ts <= w.ts - AVERAGE_S:
                total -= window.popleft().weight_kg
            if w.ts >= since:
                fat = (self.metrics(w) or {}).get("body_fat_percentage")
                points.append([w.id, w.ts, w.weight_kg, fat, round(total / len(window), 2)])
        return {"since": int(since), "points": points}

    def delete(self, weigh_in_id: int) -> dict:
        if not self.store.delete(weigh_in_id):
            raise ApiError(404, "没有这条记录")
        return {"deleted": weigh_in_id}


def _average(readings: list[WeighIn], end: float) -> float | None:
    """Mean weight over the 7 days up to `end` (exclusive start, inclusive end)."""
    kg = [w.weight_kg for w in readings if end - AVERAGE_S < w.ts <= end]
    return sum(kg) / len(kg) if kg else None
