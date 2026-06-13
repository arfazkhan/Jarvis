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
from datetime import datetime, timedelta
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
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, role TEXT, pw_hash TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, asset_id TEXT,
                signal TEXT, value REAL, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_siglog ON signal_log(building_id, asset_id, signal, ts);
            CREATE TABLE IF NOT EXISTS checklist_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, item_id TEXT,
                date TEXT, status TEXT, note TEXT, by_user TEXT, ts TEXT, verdict TEXT);
            CREATE INDEX IF NOT EXISTS ix_checklist ON checklist_responses(building_id, date, item_id);
            CREATE TABLE IF NOT EXISTS resident_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, ts TEXT,
                by_user TEXT, text TEXT, status TEXT);
            CREATE INDEX IF NOT EXISTS ix_resident_req ON resident_requests(building_id, status, ts);
            -- Phase-0 digitized checklists: a run is one filled sheet (shift+date, or
            -- a PPM asset-block); entries are per-item (server-timestamped); signoffs
            -- are the technician→supervisor→…→president chain.
            CREATE TABLE IF NOT EXISTS checklist_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, template_id TEXT,
                asset TEXT, shift_date TEXT, technician TEXT, status TEXT,
                started_at TEXT, submitted_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_runs ON checklist_runs(building_id, shift_date, template_id);
            CREATE TABLE IF NOT EXISTS checklist_run_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, item_id TEXT,
                value TEXT, status TEXT, note TEXT, is_issue INTEGER, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_entries ON checklist_run_entries(run_id, item_id);
            CREATE TABLE IF NOT EXISTS checklist_signoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, role TEXT,
                by_user TEXT, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_signoffs ON checklist_signoffs(run_id, role);
            """)
        self._siglog_last: Dict[tuple, datetime] = {}   # (asset, signal) → last logged ts

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

    # ── Users (frontend auth) ────────────────────────────────────────────
    def create_user(self, username: str, role: str, pw_hash: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO users (username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                      (username, role, pw_hash, datetime.now().isoformat()))

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT username, role, pw_hash FROM users WHERE username=?", (username,)).fetchone()
            return dict(r) if r else None

    def count_users(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def list_users(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT username, role, created_at FROM users ORDER BY username").fetchall()
            return [dict(r) for r in rows]

    # ── Signal log (timestamped history: billing + reading verification) ──
    def log_signal(self, asset_id: str, signal: str, value, ts: Optional[datetime] = None,
                   min_interval_s: float = 600.0) -> bool:
        """Record a timestamped numeric reading, downsampled to one row per
        (asset, signal) per min_interval_s so a 20s gateway cadence doesn't bloat
        SQLite. This history backs gas billing AND checklist reading-verification."""
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        ts = ts or datetime.now()
        key = (asset_id, signal)
        last = self._siglog_last.get(key)
        if last is not None and (ts - last).total_seconds() < min_interval_s:
            return False
        self._siglog_last[key] = ts
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO signal_log (building_id, asset_id, signal, value, ts)"
                      " VALUES (?,?,?,?,?)",
                      (self.building_id, asset_id, signal, float(value), ts.isoformat(timespec="seconds")))
        return True

    def signal_near(self, asset_id: str, signal: str, ts: datetime,
                    window_s: float = 3600.0) -> Optional[Dict[str, Any]]:
        """The logged reading nearest to ts within ±window_s — None = honest no-data."""
        lo = (ts - timedelta(seconds=window_s)).isoformat(timespec="seconds")
        hi = (ts + timedelta(seconds=window_s)).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT value, ts FROM signal_log WHERE building_id=? AND asset_id=? AND signal=?"
                " AND ts BETWEEN ? AND ?", (self.building_id, asset_id, signal, lo, hi)).fetchall()
        if not rows:
            return None
        best = min(rows, key=lambda r: abs((datetime.fromisoformat(r["ts"]) - ts).total_seconds()))
        return {"value": best["value"], "ts": best["ts"]}

    def signal_range(self, asset_id: str, signal: str, start: datetime, end: datetime):
        """(first, last) logged readings in [start, end] — consumption = last − first."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT value, ts FROM signal_log WHERE building_id=? AND asset_id=? AND signal=?"
                " AND ts BETWEEN ? AND ? ORDER BY ts",
                (self.building_id, asset_id, signal,
                 start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))).fetchall()
        if not rows:
            return None
        return ({"value": rows[0]["value"], "ts": rows[0]["ts"]},
                {"value": rows[-1]["value"], "ts": rows[-1]["ts"]})

    def signal_series(self, asset_id: str, signal: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT value, ts FROM signal_log WHERE building_id=? AND asset_id=? AND signal=?"
                " ORDER BY ts DESC LIMIT ?", (self.building_id, asset_id, signal, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]

    def meters_with_history(self, signal: str = "meter_total_m3") -> List[str]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT DISTINCT asset_id FROM signal_log WHERE building_id=? AND signal=?",
                             (self.building_id, signal)).fetchall()
            return [r["asset_id"] for r in rows]

    # ── Checklist responses (physical checks + submitted readings) ────────
    def save_checklist_response(self, item_id: str, date: str, status: str, note: str = "",
                                by_user: str = "", verdict: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO checklist_responses (building_id, item_id, date, status, note,"
                      " by_user, ts, verdict) VALUES (?,?,?,?,?,?,?,?)",
                      (self.building_id, item_id, date, status, note, by_user,
                       datetime.now().isoformat(timespec="seconds"), verdict))

    def checklist_responses_for(self, date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_responses WHERE building_id=? AND date=?"
                             " ORDER BY ts", (self.building_id, date)).fetchall()
            return [dict(r) for r in rows]

    # ── Resident requests (WhatsApp 'create work order' from a resident) ──
    # The bot's confirmation text is only sent AFTER this insert returns — the
    # resident is never told 'noted' unless it actually was.
    def save_resident_request(self, by_user: str, text: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO resident_requests (building_id, ts, by_user, text, status)"
                            " VALUES (?,?,?,?,?)",
                            (self.building_id, datetime.now().isoformat(timespec="seconds"),
                             by_user, text, "open"))
            return int(cur.lastrowid)

    def resident_requests(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM resident_requests WHERE building_id=? AND status=?"
                                 " ORDER BY ts", (self.building_id, status)).fetchall()
            else:
                rows = c.execute("SELECT * FROM resident_requests WHERE building_id=?"
                                 " ORDER BY ts", (self.building_id,)).fetchall()
            return [dict(r) for r in rows]

    def set_resident_request_status(self, request_id: int, status: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE resident_requests SET status=? WHERE building_id=? AND id=?",
                      (status, self.building_id, request_id))

    # ── Phase-0 checklist runs / entries / sign-offs ─────────────────────
    def create_checklist_run(self, building_id: str, template_id: str, shift_date: str,
                             technician: str = "", asset: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO checklist_runs (building_id, template_id, asset, shift_date,"
                " technician, status, started_at, submitted_at) VALUES (?,?,?,?,?,?,?,?)",
                (building_id, template_id, asset, shift_date, technician, "open",
                 datetime.now().isoformat(timespec="seconds"), None))
            return int(cur.lastrowid)

    def find_open_run(self, building_id: str, template_id: str, shift_date: str,
                      asset: str = "") -> Optional[int]:
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT id FROM checklist_runs WHERE building_id=? AND template_id=? AND"
                " shift_date=? AND asset=? AND status='open' ORDER BY id DESC LIMIT 1",
                (building_id, template_id, shift_date, asset)).fetchone()
            return int(r["id"]) if r else None

    def get_checklist_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM checklist_runs WHERE id=?", (run_id,)).fetchone()
            return dict(r) if r else None

    def save_checklist_entry(self, run_id: int, item_id: str, value: str = "", status: str = "",
                             note: str = "", is_issue: bool = False) -> None:
        """Upsert one item's entry (operator may correct before submit). Server-timestamped."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM checklist_run_entries WHERE run_id=? AND item_id=?",
                      (run_id, item_id))
            c.execute("INSERT INTO checklist_run_entries (run_id, item_id, value, status, note,"
                      " is_issue, ts) VALUES (?,?,?,?,?,?,?)",
                      (run_id, item_id, value, status, note, 1 if is_issue else 0,
                       datetime.now().isoformat(timespec="seconds")))

    def checklist_entries(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_run_entries WHERE run_id=?", (run_id,)).fetchall()
        return {r["item_id"]: {"value": r["value"], "status": r["status"], "note": r["note"],
                               "is_issue": bool(r["is_issue"]), "ts": r["ts"]} for r in rows}

    def submit_checklist_run(self, run_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_runs SET status='submitted', submitted_at=? WHERE id=?",
                      (datetime.now().isoformat(timespec="seconds"), run_id))

    def add_checklist_signoff(self, run_id: int, role: str, by_user: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM checklist_signoffs WHERE run_id=? AND role=?", (run_id, role))
            c.execute("INSERT INTO checklist_signoffs (run_id, role, by_user, ts) VALUES (?,?,?,?)",
                      (run_id, role, by_user, datetime.now().isoformat(timespec="seconds")))

    def checklist_signoffs(self, run_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT role, by_user, ts FROM checklist_signoffs WHERE run_id=?"
                             " ORDER BY ts", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    def checklist_runs_for(self, building_id: str, shift_date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_runs WHERE building_id=? AND shift_date=?"
                             " ORDER BY id", (building_id, shift_date)).fetchall()
            return [dict(r) for r in rows]
