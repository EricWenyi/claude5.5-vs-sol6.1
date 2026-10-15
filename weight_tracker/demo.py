"""Six months of made-up weigh-ins, for trying the dashboard before logging real ones."""

from __future__ import annotations

import datetime as dt
import math
import random

from .store import Entry, Store

NOTES = {12: "出差", 47: "聚餐后", 95: "感冒", 133: "旅行回来"}


def _scale(lb: float) -> float:
    return round(lb * 5) / 5  # the scale reads in 0.2 lb steps


def fill(store: Store, days: int = 180, seed: int = 3) -> None:
    rng = random.Random(seed)
    today = dt.date.today()
    entries = []
    for i in range(days):
        date = today - dt.timedelta(days=days - 1 - i)
        # About 0.6 lb a week, a faster stretch around day 75, a holiday bump around day 110,
        # and the day-to-day water swings that make single readings misleading.
        lb = 186 - 0.6 / 7 * i - 1.5 * (1 + math.tanh((i - 75) / 10)) + 2.5 * math.exp(-(((i - 110) / 9) ** 2))
        lb += 0.6 * math.sin(i / 7 * 2 * math.pi) + rng.gauss(0, 0.6)
        morning = i == days - 1 or rng.random() > 0.18  # some mornings are forgotten
        evening = i != days - 1 and rng.random() < (0.55 if morning else 0.3)
        if morning:
            time = f"{rng.choice((6, 7, 7, 7, 8)):02d}:{rng.randrange(60):02d}"
            entries.append(Entry(date, _scale(lb), "lb", time, NOTES.get(i, "")))
        if evening:
            # A day's food and drink: usually 1-2 lb heavier by bedtime.
            time = f"{rng.choice((20, 21, 22, 22, 23)):02d}:{rng.randrange(60):02d}"
            entries.append(Entry(date, _scale(lb + rng.uniform(0.9, 2.2)), "lb", time))
    store.add_many(entries, skip_duplicates=False)
