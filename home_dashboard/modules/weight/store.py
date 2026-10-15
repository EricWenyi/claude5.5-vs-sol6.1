"""SQLite storage for weigh-ins.

Only what the scale measured is stored (weight and impedance). Body fat and the other
estimates depend on height, age and sex, so they are worked out when data is served:
changing the profile later also updates the history.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS weigh_ins (
    id        INTEGER PRIMARY KEY,
    ts        INTEGER NOT NULL,  -- unix seconds
    weight_kg REAL    NOT NULL,
    impedance INTEGER            -- ohms; missing when the scale couldn't measure it (e.g. socks)
);
CREATE INDEX IF NOT EXISTS weigh_ins_ts ON weigh_ins (ts);
"""


@dataclass(frozen=True)
class WeighIn:
    id: int
    ts: int
    weight_kg: float
    impedance: int | None


class WeightStore:
    def __init__(self, path: str):
        # One connection shared by the scale callback and the HTTP threads, serialised by a lock.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def add(self, ts: float, weight_kg: float, impedance: int | None) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO weigh_ins (ts, weight_kg, impedance) VALUES (?, ?, ?)", (int(ts), weight_kg, impedance)
            )
            return cur.lastrowid

    def since(self, ts: float) -> list[WeighIn]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, weight_kg, impedance FROM weigh_ins WHERE ts >= ? ORDER BY ts, id", (int(ts),)
            ).fetchall()
        return [WeighIn(*r) for r in rows]

    def latest(self) -> WeighIn | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, ts, weight_kg, impedance FROM weigh_ins ORDER BY ts DESC, id DESC LIMIT 1"
            ).fetchone()
        return WeighIn(*row) if row else None

    def delete(self, weigh_in_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM weigh_ins WHERE id = ?", (weigh_in_id,)).rowcount > 0
