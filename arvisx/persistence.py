"""
ArvisX persistence (Phase 7) — institutional memory that survives restarts.

Single SQLite file (stdlib, no deps). Holds:
  - events      : fault/risk history per asset → vendor 'asset history' view + skillbook input
  - baselines   : Phase-4 learned normals (warm-start → 'learns your building' is real)
  - work_orders : tickets survive a restart
  - skills      : learned fault patterns (see skillbook.py)

Everything is keyed by a building_id so one DB can hold a portfolio later. Thread-safe
via a per-call connection (check_same_thread off).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ArvisxDb:
    def __init__(self, path: Optional[str] = None, building_id: str = "default"):
        self.building_id = building_id
        self.path = path or str(Path(__file__).parent / "data" / "arvisx.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self):
        with self._lock, self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, ts TEXT,
                asset_id TEXT, asset_name TEXT, service TEXT, severity TEXT,
                message TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_events_asset ON events(building_id, asset_id, ts);
            CREATE TABLE IF NOT EXISTS baselines (
                building_id TEXT, asset_id TEXT, signal TEXT, data TEXT, updated_at TEXT,
                PRIMARY KEY (building_id, asset_id, signal));
            CREATE TABLE IF NOT EXISTS work_orders (
                building_id TEXT, wo_id TEXT, signature TEXT, status TEXT, data TEXT,
                PRIMARY KEY (building_id, wo_id));
            CREATE TABLE IF NOT EXISTS skills (
                building_id TEXT, scope TEXT, symptom TEXT, cause TEXT, action TEXT,
                confidence REAL, times_seen INTEGER, confirmed INTEGER, last_seen TEXT, source TEXT,
                PRIMARY KEY (building_id, scope, symptom));
            CREATE TABLE IF NOT EXISTS buildings (
                building_id TEXT PRIMARY KEY, name TEXT, state TEXT, data TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS investigations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, ts TEXT, asset_id TEXT,
                trigger TEXT, root_cause TEXT, recommended_action TEXT, confidence TEXT,
                source TEXT, data TEXT);
            CREATE INDEX IF NOT EXISTS ix_inv_asset ON investigations(building_id, asset_id, ts);
            CREATE TABLE IF NOT EXISTS watches (
                building_id TEXT, watch_id TEXT, asset_id TEXT, signal TEXT, reason TEXT,
                est_seconds REAL, created_at TEXT, wake_at TEXT, resolved INTEGER, data TEXT,
                PRIMARY KEY (building_id, watch_id));
            CREATE TABLE IF NOT EXISTS heartbeat_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, ts TEXT, data TEXT);
            """)

    # ── Building commissioning config ────────────────────────────────────
    def save_building(self, building_id: str, name: str, state: str, data: Dict[str, Any]):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO buildings (building_id, name, state, data, updated_at)"
                      " VALUES (?,?,?,?,?)",
                      (building_id, name, state, json.dumps(data, default=str), datetime.now().isoformat()))

    def load_building(self, building_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT data FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            return json.loads(r["data"]) if r else None

    def list_buildings(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT building_id, name, state FROM buildings ORDER BY building_id").fetchall()
            return [dict(r) for r in rows]

    # ── Events / fault history ───────────────────────────────────────────
    def log_event(self, asset_id: str, asset_name: str, service: str, severity: str,
                  message: str, detail: str = "", ts: Optional[datetime] = None):
        ts = (ts or datetime.now()).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO events (building_id, ts, asset_id, asset_name, service, severity, message, detail)"
                      " VALUES (?,?,?,?,?,?,?,?)",
                      (self.building_id, ts, asset_id, asset_name, service, severity, message, detail))

    def history(self, asset_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            if asset_id:
                rows = c.execute("SELECT * FROM events WHERE building_id=? AND asset_id=? ORDER BY ts DESC LIMIT ?",
                                 (self.building_id, asset_id, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM events WHERE building_id=? ORDER BY ts DESC LIMIT ?",
                                 (self.building_id, limit)).fetchall()
            return [dict(r) for r in rows]

    # ── Baselines (warm-start) ───────────────────────────────────────────
    def save_baseline(self, asset_id: str, signal: str, values: List[float]):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO baselines (building_id, asset_id, signal, data, updated_at)"
                      " VALUES (?,?,?,?,?)",
                      (self.building_id, asset_id, signal, json.dumps(values), datetime.now().isoformat()))

    def load_baselines(self) -> List[tuple]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT asset_id, signal, data FROM baselines WHERE building_id=?",
                             (self.building_id,)).fetchall()
            return [(r["asset_id"], r["signal"], json.loads(r["data"])) for r in rows]

    # ── Work orders ──────────────────────────────────────────────────────
    def save_work_order(self, wo_id: str, signature: str, status: str, data: Dict[str, Any]):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO work_orders (building_id, wo_id, signature, status, data)"
                      " VALUES (?,?,?,?,?)",
                      (self.building_id, wo_id, signature, status, json.dumps(data, default=str)))

    def load_work_orders(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT data FROM work_orders WHERE building_id=?", (self.building_id,)).fetchall()
            return [json.loads(r["data"]) for r in rows]

    # ── Agentic layer: investigations / watches / heartbeat (durable) ────
    def save_investigation(self, asset_id: str, trigger: str, root_cause: str,
                           recommended_action: str, confidence: str, source: str,
                           data: Dict[str, Any], ts: Optional[datetime] = None) -> None:
        ts = (ts or datetime.now()).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO investigations (building_id, ts, asset_id, trigger, root_cause, "
                      "recommended_action, confidence, source, data) VALUES (?,?,?,?,?,?,?,?,?)",
                      (self.building_id, ts, asset_id, trigger, root_cause, recommended_action,
                       confidence, source, json.dumps(data, default=str)))

    def recent_investigations(self, asset_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            if asset_id:
                rows = c.execute("SELECT * FROM investigations WHERE building_id=? AND asset_id=? "
                                 "ORDER BY id DESC LIMIT ?", (self.building_id, asset_id, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM investigations WHERE building_id=? ORDER BY id DESC LIMIT ?",
                                 (self.building_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def save_watch(self, watch_id: str, asset_id: str, signal: str, reason: str, est_seconds: float,
                   created_at: str, wake_at: str, resolved: bool, data: Dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO watches (building_id, watch_id, asset_id, signal, reason, "
                      "est_seconds, created_at, wake_at, resolved, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (self.building_id, watch_id, asset_id, signal, reason, float(est_seconds),
                       created_at, wake_at, 1 if resolved else 0, json.dumps(data, default=str)))

    def load_open_watches(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT data FROM watches WHERE building_id=? AND resolved=0 "
                             "ORDER BY wake_at", (self.building_id,)).fetchall()
            return [json.loads(r["data"]) for r in rows]

    def save_tick(self, data: Dict[str, Any], ts: Optional[datetime] = None) -> None:
        ts = (ts or datetime.now()).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO heartbeat_ticks (building_id, ts, data) VALUES (?,?,?)",
                      (self.building_id, ts, json.dumps(data, default=str)))

    def recent_ticks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT data FROM heartbeat_ticks WHERE building_id=? ORDER BY id DESC LIMIT ?",
                             (self.building_id, limit)).fetchall()
            return [json.loads(r["data"]) for r in rows]
