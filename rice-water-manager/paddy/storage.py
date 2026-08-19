"""水位・バルブ状態の記録 (SQLite)。"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   ts TEXT NOT NULL,
                   level_mm REAL NOT NULL,
                   target_mm REAL NOT NULL,
                   valve_open INTEGER NOT NULL,
                   stage TEXT
               )"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)"
        )
        self._conn.commit()

    def log_reading(self, level_mm: float, target_mm: float, valve_open: bool,
                    stage: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO readings VALUES (?, ?, ?, ?, ?)",
                (dt.datetime.now().isoformat(timespec="seconds"),
                 round(level_mm, 1), target_mm, int(valve_open), stage),
            )
            self._conn.commit()

    def history(self, hours: float = 24) -> list[dict]:
        since = (dt.datetime.now() - dt.timedelta(hours=hours)).isoformat(
            timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, level_mm, target_mm, valve_open, stage "
                "FROM readings WHERE ts >= ? ORDER BY ts", (since,)
            ).fetchall()
        return [
            {"ts": r[0], "level_mm": r[1], "target_mm": r[2],
             "valve_open": bool(r[3]), "stage": r[4]}
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
