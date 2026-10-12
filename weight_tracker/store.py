"""SQLite storage for weigh-ins.

Each weigh-in is stored exactly as it was read off the scale (number and unit), so
switching the dashboard between lb and kg never rounds away what was typed in.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

KG_PER_LB = 0.45359237
UNITS = ("lb", "kg")

# Anything outside this is a typo or the wrong unit, not a body weight.
MIN_KG, MAX_KG = 10.0, 350.0
MAX_NOTE = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id      INTEGER PRIMARY KEY,
    date    TEXT    NOT NULL,  -- local date of the weigh-in, YYYY-MM-DD
    time    TEXT,              -- local time, HH:MM, when known
    weight  REAL    NOT NULL,  -- as shown on the scale
    unit    TEXT    NOT NULL,  -- 'lb' or 'kg'
    note    TEXT    NOT NULL DEFAULT '',
    created INTEGER NOT NULL   -- unix seconds
);
CREATE INDEX IF NOT EXISTS entries_date ON entries (date);
"""


@dataclass(frozen=True)
class Entry:
    date: dt.date
    weight: float
    unit: str = "lb"
    time: str | None = None
    note: str = ""
    id: int | None = None

    @property
    def kg(self) -> float:
        return self.weight * KG_PER_LB if self.unit == "lb" else self.weight

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "time": self.time,
            "weight": self.weight,
            "unit": self.unit,
            "kg": round(self.kg, 3),
            "note": self.note,
        }


def from_kg(kg: float, unit: str) -> float:
    return kg / KG_PER_LB if unit == "lb" else kg


def validate(e: Entry, today: dt.date | None = None) -> None:
    """Raise ValueError (with a message for the user) if `e` can't be a real weigh-in."""
    today = today or dt.date.today()
    if e.unit not in UNITS:
        raise ValueError(f"单位只能是 lb 或 kg，收到的是 {e.unit!r}")
    if not math.isfinite(e.weight) or not MIN_KG <= e.kg <= MAX_KG:
        lo, hi = (round(from_kg(v, e.unit)) for v in (MIN_KG, MAX_KG))
        raise ValueError(f"{e.weight:g} {e.unit} 不像是体重（合理范围 {lo}–{hi} {e.unit}），是不是单位选错了？")
    if e.date > today + dt.timedelta(days=1) or e.date.year < 1900:
        raise ValueError(f"日期 {e.date.isoformat()} 不对，不能晚于今天")
    if e.time is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", e.time):
        raise ValueError(f"时间 {e.time!r} 格式不对，应为 HH:MM")
    if len(e.note) > MAX_NOTE:
        raise ValueError(f"备注最多 {MAX_NOTE} 个字")


def _same(a: Entry, b: Entry) -> bool:
    return a.date == b.date and (a.time or "") == (b.time or "") and abs(a.kg - b.kg) < 0.01


class Store:
    def __init__(self, path: str):
        # One connection shared by the HTTP threads, serialised by a lock.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def add(self, e: Entry) -> int:
        with self._lock, self._db:
            return self._insert(e)

    def add_many(self, entries: list[Entry], skip_duplicates: bool = True) -> tuple[int, int]:
        """Insert `entries`; returns (added, skipped as duplicates).

        A duplicate is an entry with the same date, time and weight as one already
        stored (or earlier in the same batch), so importing a file twice adds nothing.
        """
        added = skipped = 0
        with self._lock, self._db:
            seen = self._all() if skip_duplicates else []
            for e in entries:
                if skip_duplicates and any(_same(e, s) for s in seen if s.date == e.date):
                    skipped += 1
                    continue
                self._insert(e)
                seen.append(e)
                added += 1
        return added, skipped

    def entries(self) -> list[Entry]:
        """All weigh-ins, oldest first."""
        with self._lock:
            return self._all()

    def delete(self, entry_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _insert(self, e: Entry) -> int:
        cur = self._db.execute(
            "INSERT INTO entries (date, time, weight, unit, note, created) VALUES (?, ?, ?, ?, ?, ?)",
            (e.date.isoformat(), e.time, e.weight, e.unit, e.note, int(time.time())),
        )
        return cur.lastrowid

    def _all(self) -> list[Entry]:
        rows = self._db.execute(
            "SELECT id, date, time, weight, unit, note FROM entries ORDER BY date, COALESCE(time, ''), id"
        ).fetchall()
        return [Entry(dt.date.fromisoformat(d), w, u, t, n, i) for i, d, t, w, u, n in rows]
