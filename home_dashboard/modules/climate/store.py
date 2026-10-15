"""SQLite storage for sensor samples and manual reference checks.

Readings are stored exactly as the sensor broadcast them. Calibration offsets
are applied when data is served, so changing an offset later also corrects the
history that was already recorded.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    ts       INTEGER NOT NULL,  -- unix seconds
    device   TEXT    NOT NULL,
    temp_c   REAL    NOT NULL,
    humidity REAL    NOT NULL,
    battery  INTEGER,
    rssi     INTEGER
);
CREATE INDEX IF NOT EXISTS readings_ts ON readings (ts);

-- A reading taken off another thermometer's screen (e.g. the AcuRite),
-- paired with the sensor's raw reading at the same moment.
CREATE TABLE IF NOT EXISTS reference_checks (
    id              INTEGER PRIMARY KEY,
    ts              INTEGER NOT NULL,
    ref_temp_c      REAL    NOT NULL,
    ref_humidity    REAL    NOT NULL,
    sensor_temp_c   REAL    NOT NULL,
    sensor_humidity REAL    NOT NULL
);
"""


@dataclass(frozen=True)
class Sample:
    ts: float
    device: str
    temp_c: float
    humidity: float
    battery: int | None = None
    rssi: int | None = None


class Store:
    def __init__(self, path: str):
        # One connection shared by the collector and the HTTP threads, serialised by a lock.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def add_reading(self, s: Sample) -> None:
        self.add_readings([s])

    def add_readings(self, samples: list[Sample]) -> None:
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
                [(int(s.ts), s.device, s.temp_c, s.humidity, s.battery, s.rssi) for s in samples],
            )

    def latest_reading(self) -> Sample | None:
        with self._lock:
            row = self._db.execute(
                "SELECT ts, device, temp_c, humidity, battery, rssi FROM readings ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        return Sample(*row) if row else None

    def history(self, since: int, bucket: int) -> list[tuple[int, float, float]]:
        """Average readings into `bucket`-second slots: [(mean_ts, temp_c, humidity), ...].

        Each point is placed at the mean time of its readings rather than the slot start,
        so the first point never lands before `since` and the last one is current.
        """
        with self._lock:
            return self._db.execute(
                """
                SELECT CAST(AVG(ts) AS INTEGER), AVG(temp_c), AVG(humidity)
                FROM readings WHERE ts >= :since
                GROUP BY ts / :b ORDER BY ts / :b
                """,
                {"b": bucket, "since": since},
            ).fetchall()

    def stats(self, since: int) -> dict | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT MIN(temp_c), AVG(temp_c), MAX(temp_c),
                       MIN(humidity), AVG(humidity), MAX(humidity), COUNT(*)
                FROM readings WHERE ts >= ?
                """,
                (since,),
            ).fetchone()
        if not row[-1]:
            return None
        return {
            "temp_c": {"min": row[0], "avg": row[1], "max": row[2]},
            "humidity": {"min": row[3], "avg": row[4], "max": row[5]},
        }

    def add_check(self, ts: float, ref_temp_c: float, ref_humidity: float, sensor: Sample) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO reference_checks (ts, ref_temp_c, ref_humidity, sensor_temp_c, sensor_humidity)"
                " VALUES (?, ?, ?, ?, ?)",
                (int(ts), ref_temp_c, ref_humidity, sensor.temp_c, sensor.humidity),
            )
            return cur.lastrowid

    def checks(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, ref_temp_c, ref_humidity, sensor_temp_c, sensor_humidity"
                " FROM reference_checks ORDER BY ts DESC"
            ).fetchall()
        keys = ("id", "ts", "ref_temp_c", "ref_humidity", "sensor_temp_c", "sensor_humidity")
        return [dict(zip(keys, r)) for r in rows]

    def delete_check(self, check_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM reference_checks WHERE id = ?", (check_id,)).rowcount > 0
