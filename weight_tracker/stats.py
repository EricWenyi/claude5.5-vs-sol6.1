"""Daily values, rolling average, weekly/monthly averages and the trend.

Everything is built from daily values (the mean of that day's weigh-ins), so a day
with three weigh-ins counts once, the same as a day with one. Each day also keeps its
daytime and night-time means separately, for comparing the two.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from .store import Entry

ROLLING_DAYS = 7

# The trend is a straight line fitted through the last TREND_DAYS days of daily values.
# With fewer weigh-ins, or ones bunched into a few days, the slope is mostly noise.
TREND_DAYS = 28
TREND_MIN_DAYS = 4
TREND_MIN_SPAN = 7

# Weigh-ins from DAY_START_HOUR:00 up to NIGHT_START_HOUR:00 count as daytime, the rest as night.
DAY_START_HOUR = 5
NIGHT_START_HOUR = 17

ONE_DAY = dt.timedelta(days=1)


def part_of_day(time: str | None) -> str | None:
    """'day' or 'night' for an 'HH:MM' time; None when the time isn't known."""
    if not time:
        return None
    return "day" if DAY_START_HOUR <= int(time[:2]) < NIGHT_START_HOUR else "night"


@dataclass(frozen=True)
class Day:
    date: dt.date
    kg: float
    n: int  # weigh-ins that day
    day_kg: float | None = None  # mean of the daytime weigh-ins
    night_kg: float | None = None  # mean of the night-time weigh-ins
    readings: tuple[tuple[str | None, float], ...] = ()  # every weigh-in as (time, kg), in time order

    @property
    def low(self) -> float:
        return min((kg for _, kg in self.readings), default=self.kg)

    @property
    def high(self) -> float:
        return max((kg for _, kg in self.readings), default=self.kg)


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date  # inclusive
    days: int  # days with at least one weigh-in
    avg: float
    min: float
    max: float
    change: float | None  # avg minus the previous period's avg; None if that period has no weigh-ins


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def daily(entries: list[Entry]) -> list[Day]:
    """One Day per date with a weigh-in, oldest first. `entries` must be in time order within a day."""
    by_date: dict[dt.date, list[Entry]] = {}
    for e in entries:
        by_date.setdefault(e.date, []).append(e)
    return [
        Day(
            date=d,
            kg=_mean([e.kg for e in es]),
            n=len(es),
            day_kg=_mean([e.kg for e in es if part_of_day(e.time) == "day"]),
            night_kg=_mean([e.kg for e in es if part_of_day(e.time) == "night"]),
            readings=tuple((e.time, e.kg) for e in es),
        )
        for d, es in sorted(by_date.items())
    ]


def rolling(days: list[Day], window: int = ROLLING_DAYS) -> list[float]:
    """For each day, the mean of the daily values in the `window` calendar days ending that day."""
    out = []
    start = 0
    for i, d in enumerate(days):
        while days[start].date <= d.date - dt.timedelta(days=window):
            start += 1
        span = days[start : i + 1]
        out.append(sum(x.kg for x in span) / len(span))
    return out


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())  # Monday


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _next_month(d: dt.date) -> dt.date:
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _periods(days: list[Day], start_of: Callable, next_start: Callable) -> list[Period]:
    groups: dict[dt.date, list[float]] = {}
    for d in days:
        groups.setdefault(start_of(d.date), []).append(d.kg)
    avgs = {start: sum(kgs) / len(kgs) for start, kgs in groups.items()}
    out = []
    for start, kgs in groups.items():
        prev = start_of(start - ONE_DAY)
        out.append(
            Period(
                start=start,
                end=next_start(start) - ONE_DAY,
                days=len(kgs),
                avg=avgs[start],
                min=min(kgs),
                max=max(kgs),
                change=avgs[start] - avgs[prev] if prev in avgs else None,
            )
        )
    return out


def weekly(days: list[Day]) -> list[Period]:
    """Monday-to-Sunday weeks, oldest first."""
    return _periods(days, week_start, lambda s: s + dt.timedelta(days=7))


def monthly(days: list[Day]) -> list[Period]:
    """Calendar months, oldest first."""
    return _periods(days, month_start, _next_month)


def trend(days: list[Day], window: int = TREND_DAYS) -> dict | None:
    """Least-squares slope of the daily values in the last `window` days, in kg per week.

    The window ends at the latest weigh-in, not today, so a break in logging doesn't
    wipe out the trend.
    """
    if not days:
        return None
    last = days[-1].date
    pts = [d for d in days if d.date > last - dt.timedelta(days=window)]
    if len(pts) < TREND_MIN_DAYS or (last - pts[0].date).days < TREND_MIN_SPAN:
        return None
    xs = [(d.date - last).days for d in pts]
    ys = [d.kg for d in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return {"kg_per_week": slope * 7, "start": pts[0].date, "end": last, "days": len(pts)}


def _r(kg: float | None) -> float | None:
    return None if kg is None else round(kg, 3)


def _period_json(p: Period) -> dict:
    return {
        "start": p.start.isoformat(),
        "end": p.end.isoformat(),
        "days": p.days,
        "avg": _r(p.avg),
        "min": _r(p.min),
        "max": _r(p.max),
        "change": _r(p.change),
    }


def summary(entries: list[Entry]) -> dict:
    """Everything the dashboard shows, in kg, ready for JSON."""
    days = daily(entries)
    t = trend(days)
    return {
        "days": [
            {
                "date": d.date.isoformat(),
                "kg": _r(d.kg),
                "n": d.n,
                "avg7": _r(a),
                "day": _r(d.day_kg),
                "night": _r(d.night_kg),
                "low": _r(d.low),
                "high": _r(d.high),
                "readings": [[t, _r(kg)] for t, kg in d.readings],
            }
            for d, a in zip(days, rolling(days))
        ],
        "weeks": [_period_json(p) for p in weekly(days)],
        "months": [_period_json(p) for p in monthly(days)],
        "trend": t
        and {
            "kg_per_week": _r(t["kg_per_week"]),
            "start": t["start"].isoformat(),
            "end": t["end"].isoformat(),
            "days": t["days"],
        },
        "latest": entries[-1].to_json() if entries else None,
    }
