"""SQLite storage for survey scans. One file holds a whole site survey."""
from __future__ import annotations

import csv
import sqlite3
import time
from typing import Iterable, List, Optional

from .scanner import AccessPoint

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id        INTEGER PRIMARY KEY,
    ts        REAL NOT NULL,
    location  TEXT NOT NULL,
    x         REAL,
    y         REAL,
    iface     TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    scan_id        INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    bssid          TEXT NOT NULL,
    ssid           TEXT NOT NULL,
    freq           INTEGER NOT NULL,
    channel        INTEGER NOT NULL,
    band           TEXT NOT NULL,
    signal         REAL NOT NULL,
    security       TEXT,
    station_count  INTEGER,
    utilization    REAL,
    width          INTEGER
);
CREATE INDEX IF NOT EXISTS obs_scan ON observations(scan_id);
"""

OBS_FIELDS = ["bssid", "ssid", "freq", "channel", "band", "signal", "security",
              "station_count", "utilization", "width"]


class Survey:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def add_scan(self, location: str, aps: Iterable[AccessPoint], iface: str = "",
                 x: Optional[float] = None, y: Optional[float] = None,
                 ts: Optional[float] = None) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO scans (ts, location, x, y, iface) VALUES (?,?,?,?,?)",
                (ts or time.time(), location, x, y, iface),
            )
            scan_id = cur.lastrowid
            self.db.executemany(
                f"INSERT INTO observations (scan_id, {', '.join(OBS_FIELDS)}) "
                f"VALUES (?, {', '.join('?' * len(OBS_FIELDS))})",
                [(scan_id, *(getattr(ap, f) for f in OBS_FIELDS)) for ap in aps],
            )
        return scan_id

    def locations(self) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT location, COUNT(*) AS scans, MIN(ts) AS first, MAX(ts) AS last,"
            " AVG(x) AS x, AVG(y) AS y FROM scans GROUP BY location ORDER BY MIN(ts)"
        ).fetchall()

    def scans(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM scans ORDER BY ts").fetchall()

    def observations(self) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT s.location, s.ts, o.* FROM observations o "
            "JOIN scans s ON s.id = o.scan_id ORDER BY s.ts"
        ).fetchall()

    def delete_location(self, location: str) -> int:
        with self.db:
            return self.db.execute(
                "DELETE FROM scans WHERE location = ?", (location,)
            ).rowcount

    def export_csv(self, out_path: str) -> int:
        rows = self.observations()
        with open(out_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["location", "timestamp"] + OBS_FIELDS)
            for r in rows:
                w.writerow([r["location"],
                            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))]
                           + [r[k] for k in OBS_FIELDS])
        return len(rows)
