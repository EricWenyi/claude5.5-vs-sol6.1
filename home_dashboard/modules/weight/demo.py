"""Simulated weigh-ins, for trying the 体重 tab without a scale."""

from __future__ import annotations

import math
import random
import time

from .api import Profile
from .store import WeightStore

DEMO_PROFILE = Profile(height_cm=178, age=30, sex="male")


def add_demo_weigh_ins(store: WeightStore, days: int = 90) -> None:
    """One weigh-in most mornings, drifting down by about 2 kg over the period."""
    rng = random.Random(11)
    now = time.time()
    for d in range(days, -1, -1):
        if d and rng.random() < 0.2:  # some days are skipped
            continue
        progress = (days - d) / days
        kg = 79.2 - 1.9 * progress + 0.3 * math.sin(d / 3.5) + rng.gauss(0, 0.25)
        impedance = int(532 - 10 * progress + rng.gauss(0, 6))
        store.add(now - d * 86400 - rng.uniform(0, 1800), round(kg, 2), impedance)
