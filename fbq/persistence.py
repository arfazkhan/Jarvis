"""
fbq persistence — SQLite, same discipline as arvisx: one class, guarded migrations,
every write provenance-stamped. The message table IS the event log (C13): raw turn →
extraction → action are all replayable rows.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class FbqDb:
    def __init__(self, path: str = ""):
        self.path = path or os.environ.get("FBQ_DB", "fbq/data/fbq.db")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        with self._lock, self._conn() as c:
            c.executescript("""
            -- A client project: one hosted/linked WhatsApp group, one plan.
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phase TEXT,
                start_date TEXT, working_days_only INTEGER DEFAULT 0,
                group_jid TEXT, active INTEGER DEFAULT 1, created_at TEXT);
            -- The live plan (ProjectPlan JSON — engine loads/modifies/saves whole).
            CREATE TABLE IF NOT EXISTS plans (
                project_id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT);
            -- C13 event log: every ingested group message, replayable.
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
                sender_phone TEXT, sender_name TEXT, kind TEXT, text TEXT,
                media_ref TEXT, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_msgs ON messages(project_id, ts);
            -- C5 extractions + C7 lane state. status: pending|confirmed|declined|auto|expired.
            CREATE TABLE IF NOT EXISTS extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, message_id INTEGER,
                type TEXT, payload TEXT, confidence REAL, lane TEXT,
                status TEXT DEFAULT 'pending', created_at TEXT, decided_at TEXT, decided_by TEXT);
            CREATE INDEX IF NOT EXISTS ix_extr ON extractions(project_id, status);
            -- Outbound queue — the bot polls + delivers + acks (same pattern as arvisx).
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
                to_jid TEXT, text TEXT, kind TEXT, sent INTEGER DEFAULT 0, created_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_outbox ON outbox(sent);
            -- C12 identity: number ↔ person ↔ plan role, per project.
            CREATE TABLE IF NOT EXISTS people (
                project_id INTEGER, phone TEXT, name TEXT, role TEXT,
                PRIMARY KEY (project_id, phone));
            -- F12 agent activity: every agent write, undoable where lane A.
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, action TEXT,
                detail TEXT, actor TEXT, lane TEXT, source_msg INTEGER, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_activity ON activity(project_id, ts);
            """)

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ── projects & plans ──────────────────────────────────────────────────
    def create_project(self, name: str, phase: str, start_date: str, group_jid: str = "",
                       working_days_only: bool = False) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO projects (name, phase, start_date, working_days_only,"
                            " group_jid, created_at) VALUES (?,?,?,?,?,?)",
                            (name, phase, start_date, 1 if working_days_only else 0,
                             group_jid, self._now()))
            return int(cur.lastrowid)

    def list_projects(self, active_only: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM projects" + (" WHERE active=1" if active_only else "") + " ORDER BY id DESC"
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return dict(r) if r else None

    def project_by_group(self, group_jid: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM projects WHERE group_jid=? AND active=1"
                          " ORDER BY id DESC LIMIT 1", (group_jid,)).fetchone()
            return dict(r) if r else None

    def link_group(self, project_id: int, group_jid: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE projects SET group_jid=? WHERE id=?", (group_jid, project_id))

    def save_plan(self, project_id: int, plan_dict: Dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO plans (project_id, data, updated_at) VALUES (?,?,?)",
                      (project_id, json.dumps(plan_dict, default=str), self._now()))

    def load_plan(self, project_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT data FROM plans WHERE project_id=?", (project_id,)).fetchone()
            return json.loads(r["data"]) if r else None

    # ── messages (C13 event log) ──────────────────────────────────────────
    def log_message(self, project_id: int, sender_phone: str, sender_name: str,
                    kind: str, text: str, media_ref: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO messages (project_id, sender_phone, sender_name, kind,"
                            " text, media_ref, ts) VALUES (?,?,?,?,?,?,?)",
                            (project_id, sender_phone, sender_name, kind, text[:2000],
                             media_ref, self._now()))
            return int(cur.lastrowid)

    def recent_messages(self, project_id: int, limit: int = 40) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM messages WHERE project_id=? ORDER BY id DESC LIMIT ?",
                             (project_id, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]

    def messages_on(self, project_id: int, date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM messages WHERE project_id=? AND substr(ts,1,10)=? "
                             "ORDER BY id ASC", (project_id, date)).fetchall()
            return [dict(r) for r in rows]

    # ── extractions & lanes (C5/C7) ───────────────────────────────────────
    def add_extraction(self, project_id: int, message_id: int, etype: str,
                       payload: Dict[str, Any], confidence: float, lane: str,
                       status: str = "pending") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO extractions (project_id, message_id, type, payload,"
                            " confidence, lane, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (project_id, message_id, etype, json.dumps(payload, default=str),
                             confidence, lane, status, self._now()))
            return int(cur.lastrowid)

    def pending_extractions(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM extractions WHERE status='pending'"
        args: List[Any] = []
        if project_id is not None:
            q += " AND project_id=?"; args.append(project_id)
        q += " ORDER BY id ASC"
        with self._lock, self._conn() as c:
            out = []
            for r in c.execute(q, tuple(args)).fetchall():
                d = dict(r); d["payload"] = json.loads(d["payload"] or "{}")
                out.append(d)
            return out

    def latest_pending_for(self, project_id: int, phone: str) -> Optional[Dict[str, Any]]:
        """The newest pending Lane-B ask addressed to this sender (their YES/NO resolves it)."""
        for e in reversed(self.pending_extractions(project_id)):
            if (e["payload"].get("confirm_phone") or "") == phone:
                return e
        return None

    def decide_extraction(self, extraction_id: int, status: str, by: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE extractions SET status=?, decided_at=?, decided_by=? WHERE id=?",
                      (status, self._now(), by, extraction_id))

    def get_extraction(self, extraction_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM extractions WHERE id=?", (extraction_id,)).fetchone()
            if not r:
                return None
            d = dict(r); d["payload"] = json.loads(d["payload"] or "{}")
            return d

    # ── outbox (bot delivery queue) ───────────────────────────────────────
    def enqueue(self, project_id: int, to_jid: str, text: str, kind: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO outbox (project_id, to_jid, text, kind, created_at)"
                            " VALUES (?,?,?,?,?)", (project_id, to_jid, text, kind, self._now()))
            return int(cur.lastrowid)

    def outbox_pending(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM outbox WHERE sent=0 ORDER BY id ASC LIMIT 50").fetchall()]

    def outbox_ack(self, ids: List[int]) -> None:
        if not ids:
            return
        ph = ",".join("?" for _ in ids)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE outbox SET sent=1 WHERE id IN ({ph})", tuple(ids))

    # ── people (C12) ──────────────────────────────────────────────────────
    def upsert_person(self, project_id: int, phone: str, name: str = "", role: str = "") -> None:
        with self._lock, self._conn() as c:
            old = c.execute("SELECT name, role FROM people WHERE project_id=? AND phone=?",
                            (project_id, phone)).fetchone()
            c.execute("INSERT OR REPLACE INTO people (project_id, phone, name, role) VALUES (?,?,?,?)",
                      (project_id, phone,
                       name or (old["name"] if old else ""),
                       role or (old["role"] if old else "")))

    def people(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM people WHERE project_id=?", (project_id,)).fetchall()]

    def person(self, project_id: int, phone: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM people WHERE project_id=? AND phone=?",
                          (project_id, phone)).fetchone()
            return dict(r) if r else None

    # ── activity (F12) ────────────────────────────────────────────────────
    def log_activity(self, project_id: int, action: str, detail: str, actor: str,
                     lane: str = "", source_msg: int = 0) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO activity (project_id, action, detail, actor, lane,"
                            " source_msg, ts) VALUES (?,?,?,?,?,?,?)",
                            (project_id, action, detail[:500], actor, lane, source_msg, self._now()))
            return int(cur.lastrowid)

    def activities(self, project_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM activity WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (project_id, limit)).fetchall()]
