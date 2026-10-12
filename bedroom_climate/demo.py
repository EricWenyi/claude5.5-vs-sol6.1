"""Simulated bedroom readings, for trying the dashboard without a sensor."""

from __future__ import annotations

import asyncio
import math
import random
import time

from .store import Sample, Store

DEVICE = "GVH5075_DEMO"


def _simulate(ts: float, rng: random.Random) -> Sample:
    hour = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
    day = ts / 86400
    # Warmest mid-afternoon, coolest before dawn; humidity moves the other way.
    daily = math.cos((hour - 15) / 24 * 2 * math.pi)
    weather = math.sin(day / 3.1 * 2 * math.pi)
    temp_c = 20.5 + 1.6 * daily + 0.8 * weather + rng.gauss(0, 0.08)
    humidity = 46 - 5 * daily + 4 * weather + rng.gauss(0, 0.6)
    return Sample(ts=ts, device=DEVICE, temp_c=round(temp_c, 1), humidity=round(humidity, 1), battery=87, rssi=-64)


class DemoCollector:
    def __init__(self, store: Store, interval_s: int = 60, days: int = 30):
        self.store = store
        self.interval_s = interval_s
        self._rng = random.Random(7)
        now = time.time()
        self.store.add_readings(
            [_simulate(ts, self._rng) for ts in range(int(now - days * 86400), int(now), interval_s)]
        )
        self.latest = _simulate(now, self._rng)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            self.latest = _simulate(time.time(), self._rng)
            self.store.add_reading(self.latest)
