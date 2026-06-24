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
            -- phone (→ WhatsApp manager privileges) + active flag; migration for existing DBs below.
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
            -- Resident roster (A3): pre-registered residents who may raise common-area
            -- tickets via WhatsApp. Identity keyed by phone; unit for accountability.
            CREATE TABLE IF NOT EXISTS residents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, unit TEXT,
                name TEXT, phone TEXT, active INTEGER, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_residents ON residents(building_id, active);
            -- Phase-0 digitized checklists: a run is one filled sheet (shift+date, or
            -- a PPM asset-block); entries are per-item (server-timestamped); signoffs
            -- are the technician→supervisor→…→president chain.
            CREATE TABLE IF NOT EXISTS checklist_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, template_id TEXT,
                asset TEXT, shift_date TEXT, technician TEXT, status TEXT,
                started_at TEXT, submitted_at TEXT, assignee TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_runs ON checklist_runs(building_id, shift_date, template_id);
            -- Technician roster: the manager assigns shift-rounds/issues to a named tech
            -- from this list, so a task is owned by its assignee, not bound to one person.
            CREATE TABLE IF NOT EXISTS technicians (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, name TEXT,
                phone TEXT, active INTEGER, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_techs ON technicians(building_id, active);
            -- Outbound WhatsApp notifications the bot polls + delivers. to_number set =
            -- DM that number (e.g. assigned technician); blank = broadcast to ops (manager).
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, to_number TEXT,
                kind TEXT, text TEXT, status TEXT, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_notif ON notifications(status, id);
            -- Usage + cost metrics: WhatsApp messages (in/out) + LLM calls (tokens/cost).
            -- One row per event; the admin panel aggregates over a window.
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, building_id TEXT, kind TEXT,
                channel TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
                n INTEGER, cost REAL);
            CREATE INDEX IF NOT EXISTS ix_usage ON usage_events(ts, kind);
            -- Memory candidates: LEARNED lessons AllGud proposes (recurring pattern, RCA, etc.)
            -- The manager approves/rejects before they become trusted building memory the bot
            -- recalls. dedup_key prevents re-proposing the same thing.
            CREATE TABLE IF NOT EXISTS memory_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, kind TEXT, dedup_key TEXT,
                title TEXT, detail TEXT, status TEXT, source TEXT,
                created_at TEXT, decided_at TEXT, decided_by TEXT);
            CREATE INDEX IF NOT EXISTS ix_memcand ON memory_candidates(building_id, status);
            -- Knowledge requests: when an issue is fixed with NO cause note, AllGud asks the
            -- resolver "what was the fix?" — gently nudges (≤3), then lets go. The reply becomes
            -- the resolution note → a learned lesson.
            CREATE TABLE IF NOT EXISTS knowledge_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, issue_id INTEGER,
                ask_number TEXT, subject TEXT, status TEXT, nudges INTEGER,
                created_at TEXT, last_nudge_at TEXT, answered_at TEXT, answer TEXT);
            CREATE INDEX IF NOT EXISTS ix_kreq ON knowledge_requests(building_id, status);
            -- PPM schedule per asset: date-based (interval_days) and/or condition-based
            -- (run_hours_limit). Phase-S — drives the PPM planner + compliance.
            CREATE TABLE IF NOT EXISTS ppm_schedule (
                building_id TEXT, asset TEXT, interval_days INTEGER, last_done TEXT,
                run_hours_limit REAL, updated_at TEXT, PRIMARY KEY (building_id, asset));
            -- Checklist builder: manager-defined custom templates (full Template JSON),
            -- layered over the code defaults by checklist_forms.templates_for.
            CREATE TABLE IF NOT EXISTS checklist_templates (
                building_id TEXT, template_id TEXT, data TEXT, updated_at TEXT,
                PRIMARY KEY (building_id, template_id));
            -- Scheduled checklists (B2): fire a template at a date+time, once or recurring
            -- (daily/weekly/monthly). The heartbeat opens a run (+assigns/DMs) when due;
            -- last_fired (YYYY-MM-DD) dedups so each occurrence fires once.
            CREATE TABLE IF NOT EXISTS scheduled_checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, template_id TEXT,
                label TEXT, mode TEXT, run_date TEXT, run_time TEXT, recur TEXT,
                dow INTEGER, dom INTEGER, assignee TEXT, active INTEGER DEFAULT 1,
                last_fired TEXT, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_sched ON scheduled_checklists(building_id, active);
            -- Vendor registry (AMC / service vendors an issue can be owned by).
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, name TEXT,
                category TEXT, contact TEXT, active INTEGER, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_vendors ON vendors(building_id, active);
            -- Per-building SLA config (hours) by priority; defaults applied when absent.
            CREATE TABLE IF NOT EXISTS sla_config (
                building_id TEXT, priority TEXT, response_hours REAL, resolution_hours REAL,
                PRIMARY KEY (building_id, priority));
            -- Vision (Phase D): an extraction PROPOSAL from a photo, pending operator
            -- confirmation before it's written to a checklist entry (verify pattern).
            CREATE TABLE IF NOT EXISTS vision_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, photo TEXT, kind TEXT,
                extracted TEXT, status TEXT, run_id INTEGER, item_id TEXT,
                confirmed_value TEXT, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_vision ON vision_suggestions(building_id, status);
            CREATE TABLE IF NOT EXISTS checklist_run_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, item_id TEXT,
                value TEXT, status TEXT, note TEXT, is_issue INTEGER, ts TEXT, photo TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_entries ON checklist_run_entries(run_id, item_id);
            CREATE TABLE IF NOT EXISTS checklist_signoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, role TEXT,
                by_user TEXT, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_signoffs ON checklist_signoffs(run_id, role);
            -- Tracked issues with a lifecycle (open→assigned→in_progress→resolved) +
            -- photo evidence + a transition history. source=auto (from a flagged entry)
            -- or manual (logged directly).
            CREATE TABLE IF NOT EXISTS checklist_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, run_id INTEGER,
                item_id TEXT, asset TEXT, title TEXT, detail TEXT, status TEXT, severity TEXT,
                source TEXT, assignee TEXT, raised_by TEXT, photo TEXT,
                created_at TEXT, updated_at TEXT, history TEXT);
            CREATE INDEX IF NOT EXISTS ix_cl_issues ON checklist_issues(building_id, status);
            """)
            # Defensive migration for DBs created before `assignee` existed.
            cols = [r[1] for r in c.execute("PRAGMA table_info(checklist_runs)").fetchall()]
            if "assignee" not in cols:
                c.execute("ALTER TABLE checklist_runs ADD COLUMN assignee TEXT")
            if "reminded_level" not in cols:
                c.execute("ALTER TABLE checklist_runs ADD COLUMN reminded_level INTEGER DEFAULT 0")
            tcols = [r[1] for r in c.execute("PRAGMA table_info(technicians)").fetchall()]
            if tcols and "pin_hash" not in tcols:
                c.execute("ALTER TABLE technicians ADD COLUMN pin_hash TEXT")
            # SLA/vendor columns on issues (added later than the table).
            icols = [r[1] for r in c.execute("PRAGMA table_info(checklist_issues)").fetchall()]
            for col, decl in (("priority", "TEXT"), ("vendor", "TEXT"),
                              ("escalated_level", "INTEGER DEFAULT 0")):
                if col not in icols:
                    c.execute(f"ALTER TABLE checklist_issues ADD COLUMN {col} {decl}")
            # Asset registry (explicit, manageable) — distinct from assets derived from
            # checklist item tags. Used as the asset picker for PPM + the builder.
            c.execute("""CREATE TABLE IF NOT EXISTS building_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, building_id TEXT, name TEXT,
                kind TEXT, location TEXT, active INTEGER DEFAULT 1, created_at TEXT)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_bassets ON building_assets(building_id, active)")
            # B1: a manual/datasheet doc attached to an asset (migration for existing DBs)
            for col in ("manual_path TEXT", "manual_name TEXT"):
                try:
                    c.execute(f"ALTER TABLE building_assets ADD COLUMN {col}")
                except Exception:
                    pass
            # Users get a phone (→ WhatsApp manager privileges) + active flag (migration).
            for col in ("phone TEXT", "active INTEGER DEFAULT 1"):
                try:
                    c.execute(f"ALTER TABLE users ADD COLUMN {col}")
                except Exception:
                    pass
            # C1: structured knowledge distilled from an asset's manual (specs/PPM/troubleshoot)
            c.execute("""CREATE TABLE IF NOT EXISTS asset_knowledge (
                asset_id INTEGER PRIMARY KEY, building_id TEXT, asset_name TEXT,
                manual_name TEXT, specs TEXT, ppm TEXT, troubleshooting TEXT, extracted_at TEXT)""")
        self._siglog_last: Dict[tuple, datetime] = {}   # (asset, signal) → last logged ts

    # ── Asset registry ───────────────────────────────────────────────────
    def add_asset(self, building_id: str, name: str, kind: str = "", location: str = "") -> int:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT id FROM building_assets WHERE building_id=? AND name=?",
                          (building_id, name)).fetchone()
            if r:
                c.execute("UPDATE building_assets SET active=1, kind=?, location=? WHERE id=?",
                          (kind, location, r["id"]))
                return int(r["id"])
            cur = c.execute("INSERT INTO building_assets (building_id, name, kind, location, active, created_at)"
                            " VALUES (?,?,?,?,1,?)",
                            (building_id, name, kind, location, datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def list_assets_registry(self, building_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM building_assets WHERE building_id=?"
        if active_only:
            q += " AND active=1"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY name", (building_id,)).fetchall()]

    def set_asset_active(self, asset_id: int, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE building_assets SET active=? WHERE id=?", (1 if active else 0, asset_id))

    def get_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM building_assets WHERE id=?", (asset_id,)).fetchone()
            return dict(r) if r else None

    def set_asset_manual(self, asset_id: int, manual_path: str, manual_name: str) -> None:
        """Attach (or clear, with '') a manual/datasheet document to an asset (B1)."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE building_assets SET manual_path=?, manual_name=? WHERE id=?",
                      (manual_path, manual_name, asset_id))

    # ── Asset knowledge distilled from manuals (C1) ───────────────────────
    def save_asset_knowledge(self, asset_id: int, building_id: str, asset_name: str,
                             manual_name: str, knowledge: Dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO asset_knowledge (asset_id, building_id, asset_name,"
                " manual_name, specs, ppm, troubleshooting, extracted_at) VALUES (?,?,?,?,?,?,?,?)",
                (asset_id, building_id, asset_name, manual_name,
                 json.dumps(knowledge.get("specs") or []),
                 json.dumps(knowledge.get("ppm") or []),
                 json.dumps(knowledge.get("troubleshooting") or []),
                 datetime.now().isoformat(timespec="seconds")))

    def get_asset_knowledge(self, asset_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM asset_knowledge WHERE asset_id=?", (asset_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("specs", "ppm", "troubleshooting"):
            try:
                d[k] = json.loads(d[k] or "[]")
            except Exception:
                d[k] = []
        return d

    def get_asset_knowledge_by_name(self, building_id: str, asset_name: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT asset_id FROM asset_knowledge WHERE building_id=? AND asset_name=?",
                          (building_id, asset_name)).fetchone()
        return self.get_asset_knowledge(int(r["asset_id"])) if r else None

    # ── Scheduled checklists (B2) ─────────────────────────────────────────
    def add_schedule(self, building_id: str, template_id: str, *, label: str = "",
                     mode: str = "once", run_date: str = "", run_time: str = "09:00",
                     recur: str = "", dow: Optional[int] = None, dom: Optional[int] = None,
                     assignee: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO scheduled_checklists (building_id, template_id, label, mode, run_date,"
                " run_time, recur, dow, dom, assignee, active, last_fired, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,1,'',?)",
                (building_id, template_id, label, mode, run_date, run_time, recur, dow, dom,
                 assignee, datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def list_schedules(self, building_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM scheduled_checklists WHERE building_id=?"
        if active_only:
            q += " AND active=1"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY id DESC", (building_id,)).fetchall()]

    def get_schedule(self, schedule_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM scheduled_checklists WHERE id=?", (schedule_id,)).fetchone()
            return dict(r) if r else None

    def set_schedule_active(self, schedule_id: int, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE scheduled_checklists SET active=? WHERE id=?",
                      (1 if active else 0, schedule_id))

    def set_schedule_fired(self, schedule_id: int, fired_date: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE scheduled_checklists SET last_fired=? WHERE id=?",
                      (fired_date, schedule_id))

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
    def create_user(self, username: str, role: str, pw_hash: str, phone: str = "") -> None:
        digits = "".join(ch for ch in str(phone).split("@")[0] if ch.isdigit())
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO users (username, role, pw_hash, phone, active, created_at)"
                      " VALUES (?,?,?,?,1,?)",
                      (username, role, pw_hash, digits, datetime.now().isoformat()))

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT username, role, pw_hash FROM users WHERE username=?", (username,)).fetchone()
            return dict(r) if r else None

    def count_users(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def list_users(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT username, role, phone, active, created_at FROM users ORDER BY username").fetchall()
            return [dict(r) for r in rows]

    def set_user_active(self, username: str, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET active=? WHERE username=?", (1 if active else 0, username))

    def manager_phones(self) -> List[str]:
        """Phones of active owner/fm users → WhatsApp manager privileges (alerts + actions)."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT phone FROM users WHERE active=1 AND role IN ('owner','fm','system')"
                             " AND phone IS NOT NULL AND phone!=''").fetchall()
            return [r["phone"] for r in rows]

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
                             technician: str = "", asset: str = "", assignee: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO checklist_runs (building_id, template_id, asset, shift_date,"
                " technician, status, started_at, submitted_at, assignee) VALUES (?,?,?,?,?,?,?,?,?)",
                (building_id, template_id, asset, shift_date, technician, "open",
                 datetime.now().isoformat(timespec="seconds"), None, assignee))
            return int(cur.lastrowid)

    def assign_checklist_run(self, run_id: int, assignee: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_runs SET assignee=? WHERE id=?", (assignee, run_id))

    def set_run_reminded(self, run_id: int, level: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_runs SET reminded_level=? WHERE id=?", (int(level), run_id))

    def runs_assigned_to(self, building_id: str, assignee: str, shift_date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_runs WHERE building_id=? AND assignee=? AND"
                             " shift_date=? ORDER BY id", (building_id, assignee, shift_date)).fetchall()
            return [dict(r) for r in rows]

    # ── Technician roster ────────────────────────────────────────────────
    def add_technician(self, building_id: str, name: str, phone: str = "") -> int:
        with self._lock, self._conn() as c:
            # reactivate if the same name exists (soft-deleted), else insert
            r = c.execute("SELECT id FROM technicians WHERE building_id=? AND name=?",
                          (building_id, name)).fetchone()
            if r:
                c.execute("UPDATE technicians SET active=1, phone=? WHERE id=?", (phone, r["id"]))
                return int(r["id"])
            cur = c.execute("INSERT INTO technicians (building_id, name, phone, active, created_at)"
                            " VALUES (?,?,?,1,?)",
                            (building_id, name, phone, datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def list_technicians(self, building_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM technicians WHERE building_id=?"
        if active_only:
            q += " AND active=1"
        q += " ORDER BY name"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, (building_id,)).fetchall()]

    def set_technician_active(self, tech_id: int, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE technicians SET active=? WHERE id=?", (1 if active else 0, tech_id))

    def get_technician(self, building_id: str, name: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM technicians WHERE building_id=? AND name=?",
                          (building_id, name)).fetchone()
            return dict(r) if r else None

    def set_technician_pin(self, tech_id: int, pin_hash: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE technicians SET pin_hash=? WHERE id=?", (pin_hash, tech_id))

    # ── Resident roster (A3) — pre-registered residents who may raise tickets ─
    def add_resident(self, building_id: str, name: str, phone: str, unit: str = "") -> int:
        digits = "".join(ch for ch in str(phone).split("@")[0] if ch.isdigit())
        with self._lock, self._conn() as c:
            r = c.execute("SELECT id FROM residents WHERE building_id=? AND phone=?",
                          (building_id, digits)).fetchone()
            if r:
                c.execute("UPDATE residents SET name=?, unit=?, active=1 WHERE id=?",
                          (name, unit, r["id"]))
                return int(r["id"])
            cur = c.execute("INSERT INTO residents (building_id, unit, name, phone, active, created_at)"
                            " VALUES (?,?,?,?,1,?)",
                            (building_id, unit, name, digits, datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def list_residents(self, building_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM residents WHERE building_id=?"
        if active_only:
            q += " AND active=1"
        q += " ORDER BY unit, name"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, (building_id,)).fetchall()]

    def resident_by_phone(self, building_id: str, phone: str) -> Optional[Dict[str, Any]]:
        digits = "".join(ch for ch in str(phone).split("@")[0] if ch.isdigit())
        if not digits:
            return None
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM residents WHERE building_id=? AND phone=? AND active=1",
                          (building_id, digits)).fetchone()
            return dict(r) if r else None

    def set_resident_active(self, resident_id: int, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE residents SET active=? WHERE id=?", (1 if active else 0, resident_id))

    # ── Outbound WhatsApp notification queue (bot polls + delivers + acks) ─
    def enqueue_notification(self, building_id: str, text: str, to_number: str = "",
                             kind: str = "info") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO notifications (building_id, to_number, kind, text,"
                            " status, created_at) VALUES (?,?,?,?,?,?)",
                            (building_id, to_number, kind, text, "pending",
                             datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def pending_notifications(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT id, building_id, to_number, kind, text FROM notifications"
                             " WHERE status='pending' ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def notifications_since(self, building_id: str, kind: str, since_iso: str) -> int:
        """How many notifications of this kind were created at/after since_iso — for
        dedup of periodic sends (weekly/monthly summary fires once)."""
        with self._lock, self._conn() as c:
            r = c.execute("SELECT COUNT(*) AS n FROM notifications WHERE building_id=? AND kind=? "
                          "AND created_at >= ?", (building_id, kind, since_iso)).fetchone()
            return int(r["n"]) if r else 0

    def mark_notifications_sent(self, ids: List[int]) -> None:
        if not ids:
            return
        with self._lock, self._conn() as c:
            c.executemany("UPDATE notifications SET status='sent' WHERE id=?",
                          [(int(i),) for i in ids])

    # ── Usage + cost metrics (WhatsApp + LLM) ─────────────────────────────
    def log_usage(self, building_id: str, kind: str, *, channel: str = "", model: str = "",
                  prompt_tokens: int = 0, completion_tokens: int = 0, n: int = 1,
                  cost: float = 0.0) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO usage_events (ts, building_id, kind, channel, model, prompt_tokens,"
                " completion_tokens, n, cost) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), building_id, kind, channel, model,
                 int(prompt_tokens or 0), int(completion_tokens or 0), int(n or 0), float(cost or 0.0)))

    def usage_summary(self, since_iso: str, building_id: Optional[str] = None) -> Dict[str, Any]:
        q = ("SELECT kind, channel, model, SUM(n) n, SUM(prompt_tokens) pin,"
             " SUM(completion_tokens) pout, SUM(cost) cost FROM usage_events WHERE ts>=?")
        args: List[Any] = [since_iso]
        if building_id:
            q += " AND building_id=?"; args.append(building_id)
        q += " GROUP BY kind, channel, model"
        with self._lock, self._conn() as c:
            rows = [dict(r) for r in c.execute(q, tuple(args)).fetchall()]
        wa_in = sum(r["n"] for r in rows if r["kind"] == "whatsapp_in")
        wa_out = sum(r["n"] for r in rows if r["kind"] == "whatsapp_out")
        wa_cost = sum(r["cost"] for r in rows if (r["kind"] or "").startswith("whatsapp"))
        # Split: billable = business-initiated utility templates (out + notification);
        # free = inbound + service replies.
        wa_billable = sum(r["n"] for r in rows
                          if r["kind"] == "whatsapp_out" and r["channel"] == "notification")
        wa_free = (wa_in + wa_out) - wa_billable
        llm = [r for r in rows if r["kind"] == "llm"]
        calls = sum(r["n"] for r in llm)
        pin = sum(r["pin"] for r in llm); pout = sum(r["pout"] for r in llm)
        llm_cost = sum(r["cost"] for r in llm)
        by_channel: Dict[str, Any] = {}
        for r in llm:
            ch = by_channel.setdefault(r["channel"] or "?",
                                       {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
            ch["calls"] += r["n"]; ch["prompt_tokens"] += r["pin"]
            ch["completion_tokens"] += r["pout"]; ch["cost"] = round(ch["cost"] + r["cost"], 6)
        return {
            "whatsapp": {"in": wa_in, "out": wa_out, "total": wa_in + wa_out,
                         "billable": wa_billable, "free": wa_free, "cost": round(wa_cost, 4)},
            "llm": {"calls": calls, "prompt_tokens": pin, "completion_tokens": pout,
                    "total_tokens": pin + pout, "avg_context": (round(pin / calls) if calls else 0),
                    "cost": round(llm_cost, 4), "model": (llm[0]["model"] if llm else ""),
                    "by_channel": by_channel},
            "total_cost": round(wa_cost + llm_cost, 4),
        }

    # ── Memory candidates (learned-lesson approval queue) ─────────────────
    def add_memory_candidate(self, building_id: str, kind: str, title: str, detail: str = "",
                             source: str = "", dedup_key: str = "", status: str = "pending",
                             decided_by: str = "") -> Optional[int]:
        """Insert a candidate. Skips if one with the same dedup_key already exists in a
        non-rejected state (don't re-propose). Returns the new id, or None if skipped."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            if dedup_key:
                r = c.execute("SELECT id FROM memory_candidates WHERE building_id=? AND dedup_key=? "
                              "AND status!='rejected'", (building_id, dedup_key)).fetchone()
                if r:
                    return None
            cur = c.execute(
                "INSERT INTO memory_candidates (building_id, kind, dedup_key, title, detail, status,"
                " source, created_at, decided_at, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (building_id, kind, dedup_key, title, detail, status, source, now,
                 now if status != "pending" else None, decided_by))
            return int(cur.lastrowid)

    def list_memory_candidates(self, building_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM memory_candidates WHERE building_id=?"
        args: List[Any] = [building_id]
        if status:
            q += " AND status=?"; args.append(status)
        q += " ORDER BY id DESC"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q, tuple(args)).fetchall()]

    def get_memory_candidate(self, cand_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM memory_candidates WHERE id=?", (cand_id,)).fetchone()
            return dict(r) if r else None

    def decide_memory_candidate(self, cand_id: int, status: str, by: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE memory_candidates SET status=?, decided_at=?, decided_by=? WHERE id=?",
                      (status, datetime.now().isoformat(timespec="seconds"), by, cand_id))

    # ── Knowledge requests (ask the resolver for the cause of a note-less fix) ─
    def add_knowledge_request(self, building_id: str, issue_id: int, ask_number: str, subject: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO knowledge_requests (building_id, issue_id, ask_number, subject,"
                " status, nudges, created_at, last_nudge_at) VALUES (?,?,?,?, 'open', 0, ?, ?)",
                (building_id, issue_id, ask_number, subject, now, now))
            return int(cur.lastrowid)

    def open_knowledge_request_for(self, building_id: str, ask_number: str) -> Optional[Dict[str, Any]]:
        digits = "".join(ch for ch in str(ask_number).split("@")[0] if ch.isdigit())
        if not digits:
            return None
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM knowledge_requests WHERE building_id=? AND ask_number=? "
                          "AND status='open' ORDER BY id DESC LIMIT 1", (building_id, digits)).fetchone()
            return dict(r) if r else None

    def list_open_knowledge_requests(self, building_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM knowledge_requests WHERE building_id=? AND status='open' ORDER BY id",
                (building_id,)).fetchall()]

    def bump_knowledge_request_nudge(self, req_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE knowledge_requests SET nudges=nudges+1, last_nudge_at=? WHERE id=?",
                      (datetime.now().isoformat(timespec="seconds"), req_id))

    def close_knowledge_request(self, req_id: int, status: str, answer: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE knowledge_requests SET status=?, answered_at=?, answer=? WHERE id=?",
                      (status, datetime.now().isoformat(timespec="seconds"), answer, req_id))

    def usage_daily(self, since_iso: str, building_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = ("SELECT substr(ts,1,10) d, kind, SUM(n) n, SUM(prompt_tokens+completion_tokens) tok,"
             " SUM(cost) cost FROM usage_events WHERE ts>=?")
        args: List[Any] = [since_iso]
        if building_id:
            q += " AND building_id=?"; args.append(building_id)
        q += " GROUP BY d, kind ORDER BY d"
        days: Dict[str, Any] = {}
        with self._lock, self._conn() as c:
            for r in c.execute(q, tuple(args)).fetchall():
                d = days.setdefault(r["d"], {"date": r["d"], "wa_in": 0, "wa_out": 0,
                                             "llm_calls": 0, "llm_tokens": 0, "cost": 0.0})
                if r["kind"] == "whatsapp_in": d["wa_in"] += r["n"]
                elif r["kind"] == "whatsapp_out": d["wa_out"] += r["n"]
                elif r["kind"] == "llm":
                    d["llm_calls"] += r["n"]; d["llm_tokens"] += (r["tok"] or 0)
                d["cost"] += r["cost"]
        return [{**v, "cost": round(v["cost"], 4)} for v in days.values()]

    # ── PPM schedule (Phase S) ───────────────────────────────────────────
    def set_ppm_schedule(self, building_id: str, asset: str, interval_days: int = None,
                         last_done: str = None, run_hours_limit: float = None) -> None:
        with self._lock, self._conn() as c:
            cur = c.execute("SELECT interval_days, last_done, run_hours_limit FROM ppm_schedule"
                            " WHERE building_id=? AND asset=?", (building_id, asset)).fetchone()
            iv = interval_days if interval_days is not None else (cur["interval_days"] if cur else None)
            ld = last_done if last_done is not None else (cur["last_done"] if cur else None)
            rh = run_hours_limit if run_hours_limit is not None else (cur["run_hours_limit"] if cur else None)
            c.execute("INSERT OR REPLACE INTO ppm_schedule (building_id, asset, interval_days,"
                      " last_done, run_hours_limit, updated_at) VALUES (?,?,?,?,?,?)",
                      (building_id, asset, iv, ld, rh, datetime.now().isoformat(timespec="seconds")))

    def get_ppm_schedule(self, building_id: str, asset: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM ppm_schedule WHERE building_id=? AND asset=?",
                          (building_id, asset)).fetchone()
            return dict(r) if r else None

    def list_ppm_schedules(self, building_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM ppm_schedule WHERE building_id=? ORDER BY asset",
                             (building_id,)).fetchall()
            return [dict(r) for r in rows]

    def mark_ppm_done(self, building_id: str, asset: str, done_date: str) -> None:
        self.set_ppm_schedule(building_id, asset, last_done=done_date)

    def checklist_buildings(self) -> List[str]:
        """Every building with checklist activity — so the heartbeat can sweep them all."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT building_id FROM checklist_runs "
                "UNION SELECT DISTINCT building_id FROM checklist_issues").fetchall()
        return [r[0] for r in rows if r and r[0]]

    # ── Checklist builder: custom templates ──────────────────────────────
    def save_template(self, building_id: str, template_id: str, data: Dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO checklist_templates (building_id, template_id,"
                      " data, updated_at) VALUES (?,?,?,?)",
                      (building_id, template_id, json.dumps(data, default=str),
                       datetime.now().isoformat(timespec="seconds")))

    def list_templates(self, building_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT data FROM checklist_templates WHERE building_id=? ORDER BY template_id",
                             (building_id,)).fetchall()
            return [json.loads(r["data"]) for r in rows]

    def delete_template(self, building_id: str, template_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM checklist_templates WHERE building_id=? AND template_id=?",
                            (building_id, template_id))
            return cur.rowcount > 0

    # ── Vision suggestions (Phase D) ─────────────────────────────────────
    def create_vision_suggestion(self, building_id: str, photo: str, kind: str,
                                 extracted: Dict[str, Any], run_id: int = None,
                                 item_id: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO vision_suggestions (building_id, photo, kind, extracted, status,"
                " run_id, item_id, confirmed_value, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (building_id, photo, kind, json.dumps(extracted, default=str), "pending",
                 run_id, item_id, "", datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def get_vision_suggestion(self, sug_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM vision_suggestions WHERE id=?", (sug_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["extracted"] = json.loads(d.get("extracted") or "{}")
        return d

    def list_vision_suggestions(self, building_id: str, status: str = "") -> List[Dict[str, Any]]:
        q = "SELECT * FROM vision_suggestions WHERE building_id=?"
        args: List[Any] = [building_id]
        if status:
            q += " AND status=?"; args.append(status)
        q += " ORDER BY id DESC"
        with self._lock, self._conn() as c:
            rows = c.execute(q, tuple(args)).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["extracted"] = json.loads(d.get("extracted") or "{}"); out.append(d)
        return out

    def set_vision_suggestion_status(self, sug_id: int, status: str, confirmed_value: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE vision_suggestions SET status=?, confirmed_value=? WHERE id=?",
                      (status, confirmed_value, sug_id))

    # ── Asset history (Phase S): entries about an asset, newest first ────
    def asset_entries(self, building_id: str, item_ids: List[str], limit: int = 200) -> List[Dict[str, Any]]:
        if not item_ids:
            return []
        ph = ",".join("?" for _ in item_ids)
        q = (f"SELECT e.item_id, e.value, e.status, e.note, e.is_issue, e.ts, e.photo,"
             f" r.shift_date, r.template_id FROM checklist_run_entries e"
             f" JOIN checklist_runs r ON e.run_id=r.id"
             f" WHERE r.building_id=? AND e.item_id IN ({ph})"
             f" ORDER BY e.ts DESC, e.id DESC LIMIT ?")
        with self._lock, self._conn() as c:
            rows = c.execute(q, (building_id, *item_ids, limit)).fetchall()
            return [dict(r) for r in rows]

    def find_open_run(self, building_id: str, template_id: str, shift_date: str,
                      asset: str = "") -> Optional[int]:
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT id FROM checklist_runs WHERE building_id=? AND template_id=? AND"
                " shift_date=? AND asset=? AND status='open' ORDER BY id DESC LIMIT 1",
                (building_id, template_id, shift_date, asset)).fetchone()
            return int(r["id"]) if r else None

    def last_assignee_for(self, building_id: str, template_id: str) -> str:
        """The technician most recently assigned this template — to carry forward when
        auto-opening today's recurring round."""
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT assignee FROM checklist_runs WHERE building_id=? AND template_id=? "
                "AND assignee IS NOT NULL AND assignee!='' ORDER BY id DESC LIMIT 1",
                (building_id, template_id)).fetchone()
            return r["assignee"] if r else ""

    def get_checklist_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM checklist_runs WHERE id=?", (run_id,)).fetchone()
            return dict(r) if r else None

    def save_checklist_entry(self, run_id: int, item_id: str, value: str = "", status: str = "",
                             note: str = "", is_issue: bool = False) -> None:
        """Upsert one item's entry (operator may correct before submit). Server-timestamped.
        Preserves any photo already attached to this item across the upsert."""
        with self._lock, self._conn() as c:
            old = c.execute("SELECT photo FROM checklist_run_entries WHERE run_id=? AND item_id=?",
                            (run_id, item_id)).fetchone()
            photo = old["photo"] if old else None
            c.execute("DELETE FROM checklist_run_entries WHERE run_id=? AND item_id=?",
                      (run_id, item_id))
            c.execute("INSERT INTO checklist_run_entries (run_id, item_id, value, status, note,"
                      " is_issue, ts, photo) VALUES (?,?,?,?,?,?,?,?)",
                      (run_id, item_id, value, status, note, 1 if is_issue else 0,
                       datetime.now().isoformat(timespec="seconds"), photo))

    def set_checklist_entry_photo(self, run_id: int, item_id: str, photo: str) -> None:
        """Attach a photo; create a stub entry if the item hasn't been filled yet so a
        photo can be added before/independent of the value."""
        with self._lock, self._conn() as c:
            r = c.execute("SELECT id FROM checklist_run_entries WHERE run_id=? AND item_id=?",
                          (run_id, item_id)).fetchone()
            if r:
                c.execute("UPDATE checklist_run_entries SET photo=? WHERE id=?", (photo, r["id"]))
            else:
                c.execute("INSERT INTO checklist_run_entries (run_id, item_id, value, status,"
                          " note, is_issue, ts, photo) VALUES (?,?,?,?,?,?,?,?)",
                          (run_id, item_id, "", "", "", 0,
                           datetime.now().isoformat(timespec="seconds"), photo))

    def checklist_entries(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_run_entries WHERE run_id=?", (run_id,)).fetchall()
        return {r["item_id"]: {"value": r["value"], "status": r["status"], "note": r["note"],
                               "is_issue": bool(r["is_issue"]), "ts": r["ts"],
                               "photo": r["photo"]} for r in rows}

    # ── Tracked issues (lifecycle + photo + history) ─────────────────────
    def create_issue(self, building_id: str, title: str, detail: str = "", *, run_id: int = None,
                     item_id: str = "", asset: str = "", severity: str = "issue",
                     source: str = "manual", raised_by: str = "", priority: str = "",
                     vendor: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        hist = json.dumps([{"ts": now, "action": "opened", "by": raised_by, "note": ""}])
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO checklist_issues (building_id, run_id, item_id, asset, title, detail,"
                " status, severity, source, assignee, raised_by, photo, created_at, updated_at,"
                " history, priority, vendor, escalated_level)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (building_id, run_id, item_id, asset, title, detail, "open", severity, source,
                 "", raised_by, None, now, now, hist, priority, vendor, 0))
            return int(cur.lastrowid)

    def set_issue_fields(self, issue_id: int, *, priority: str = None, vendor: str = None,
                         escalated_level: int = None) -> None:
        sets, args = [], []
        if priority is not None:
            sets.append("priority=?"); args.append(priority)
        if vendor is not None:
            sets.append("vendor=?"); args.append(vendor)
        if escalated_level is not None:
            sets.append("escalated_level=?"); args.append(int(escalated_level))
        if not sets:
            return
        args.append(issue_id)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE checklist_issues SET {', '.join(sets)} WHERE id=?", tuple(args))

    def append_issue_history(self, issue_id: int, action: str, by: str = "", note: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            r = c.execute("SELECT history FROM checklist_issues WHERE id=?", (issue_id,)).fetchone()
            if not r:
                return
            hist = json.loads(r["history"] or "[]")
            hist.append({"ts": now, "action": action, "by": by, "note": note})
            c.execute("UPDATE checklist_issues SET updated_at=?, history=? WHERE id=?",
                      (now, json.dumps(hist), issue_id))

    def get_issue(self, issue_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM checklist_issues WHERE id=?", (issue_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["history"] = json.loads(d.get("history") or "[]")
        return d

    def find_auto_issue(self, run_id: int, item_id: str) -> Optional[int]:
        """The open auto-created issue for a flagged entry (so we don't duplicate it)."""
        with self._lock, self._conn() as c:
            r = c.execute("SELECT id FROM checklist_issues WHERE run_id=? AND item_id=? AND"
                          " source='auto' AND status!='resolved' ORDER BY id DESC LIMIT 1",
                          (run_id, item_id)).fetchone()
            return int(r["id"]) if r else None

    def list_issues(self, building_id: str, status: str = "", asset: str = "") -> List[Dict[str, Any]]:
        q = "SELECT * FROM checklist_issues WHERE building_id=?"
        args: List[Any] = [building_id]
        if status:
            q += " AND status=?"; args.append(status)
        if asset:
            q += " AND asset=?"; args.append(asset)
        q += " ORDER BY id DESC"
        with self._lock, self._conn() as c:
            rows = c.execute(q, tuple(args)).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["history"] = json.loads(d.get("history") or "[]"); out.append(d)
        return out

    def update_issue(self, issue_id: int, *, status: str = "", assignee: str = None,
                     by: str = "", note: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            r = c.execute("SELECT status, assignee, history FROM checklist_issues WHERE id=?",
                          (issue_id,)).fetchone()
            if not r:
                return
            hist = json.loads(r["history"] or "[]")
            new_status = status or r["status"]
            new_assignee = r["assignee"] if assignee is None else assignee
            # Reopen (resolved → open) restarts the escalation clock so it can chase again.
            reopened = status == "open" and r["status"] == "resolved"
            action = ("reopened" if reopened else
                      (f"→ {status}" if status else ("assigned" if assignee is not None else "note")))
            hist.append({"ts": now, "action": action, "by": by, "note": note})
            if reopened:
                c.execute("UPDATE checklist_issues SET status=?, assignee=?, updated_at=?, history=?,"
                          " escalated_level=0 WHERE id=?",
                          (new_status, new_assignee, now, json.dumps(hist), issue_id))
            else:
                c.execute("UPDATE checklist_issues SET status=?, assignee=?, updated_at=?, history=? WHERE id=?",
                          (new_status, new_assignee, now, json.dumps(hist), issue_id))

    def set_issue_photo(self, issue_id: int, photo: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_issues SET photo=?, updated_at=? WHERE id=?",
                      (photo, datetime.now().isoformat(timespec="seconds"), issue_id))

    # ── Vendor registry ──────────────────────────────────────────────────
    def add_vendor(self, building_id: str, name: str, category: str = "", contact: str = "") -> int:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT id FROM vendors WHERE building_id=? AND name=?",
                          (building_id, name)).fetchone()
            if r:
                c.execute("UPDATE vendors SET active=1, category=?, contact=? WHERE id=?",
                          (category, contact, r["id"]))
                return int(r["id"])
            cur = c.execute("INSERT INTO vendors (building_id, name, category, contact, active, created_at)"
                            " VALUES (?,?,?,?,1,?)",
                            (building_id, name, category, contact,
                             datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def list_vendors(self, building_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM vendors WHERE building_id=?" + (" AND active=1" if active_only else "")
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY name", (building_id,)).fetchall()]

    def set_vendor_active(self, vendor_id: int, active: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE vendors SET active=? WHERE id=?", (1 if active else 0, vendor_id))

    # ── SLA config (per building, per priority; defaults applied in sla.py) ─
    def set_sla_config(self, building_id: str, priority: str, response_hours: float,
                       resolution_hours: float) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO sla_config (building_id, priority, response_hours,"
                      " resolution_hours) VALUES (?,?,?,?)",
                      (building_id, priority, response_hours, resolution_hours))

    def get_sla_config(self, building_id: str) -> Dict[str, tuple]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT priority, response_hours, resolution_hours FROM sla_config"
                             " WHERE building_id=?", (building_id,)).fetchall()
        return {r["priority"]: (r["response_hours"], r["resolution_hours"]) for r in rows}

    def submit_checklist_run(self, run_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_runs SET status='submitted', submitted_at=? WHERE id=?",
                      (datetime.now().isoformat(timespec="seconds"), run_id))

    def open_runs_before(self, building_id: str, before_date: str) -> List[Dict[str, Any]]:
        """Still-open runs from a PRIOR day — candidates to lapse (no terminal otherwise)."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM checklist_runs WHERE building_id=? AND status='open'"
                             " AND shift_date<? ORDER BY id", (building_id, before_date)).fetchall()
            return [dict(r) for r in rows]

    def set_run_status(self, run_id: int, status: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE checklist_runs SET status=? WHERE id=?", (status, run_id))

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
