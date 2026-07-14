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
            -- Media (photos/PDFs/voice). The bot never interprets a photo — it ASKS what it is
            -- and stores the human's own answer as the caption (which may itself be a voice note).
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, message_id INTEGER,
                kind TEXT, path TEXT, filename TEXT, sender_phone TEXT, sender_name TEXT,
                caption TEXT DEFAULT '', asked INTEGER DEFAULT 0, nudges INTEGER DEFAULT 0,
                created_at TEXT, captioned_at TEXT);
            CREATE INDEX IF NOT EXISTS ix_media ON media(project_id, caption);
            -- The BRAIN: durable project memory. "remember X" from chat, end-of-day summaries,
            -- captured decisions. Retrievable months later via semantic search.
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, text TEXT,
                source TEXT, sender TEXT, ref_date TEXT, ts TEXT);
            CREATE INDEX IF NOT EXISTS ix_mem ON memories(project_id, ts);
            -- Embeddings over BOTH messages and memories → "what did we say about X 6 months ago".
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
                ref_kind TEXT, ref_id INTEGER, vec BLOB,
                UNIQUE(project_id, ref_kind, ref_id));
            CREATE INDEX IF NOT EXISTS ix_emb ON embeddings(project_id);
            -- A PROMISE, as a first-class thing: who said it, what, by when. Aged with a
            -- ladder so "we'll finish tomorrow" can't quietly become three weeks ago.
            CREATE TABLE IF NOT EXISTS commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, task_id TEXT,
                text TEXT, owner_name TEXT, owner_phone TEXT,
                promised_on TEXT, due_date TEXT, status TEXT DEFAULT 'open',
                nudges INTEGER DEFAULT 0, last_nudge TEXT, source_msg INTEGER,
                closed_on TEXT);
            CREATE INDEX IF NOT EXISTS ix_commit ON commitments(project_id, status);
            -- The evidence trail: who approved WHAT, when, and which message proves it.
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, text TEXT,
                approver_name TEXT, approver_phone TEXT, source_msg INTEGER,
                media_ref TEXT, approved_on TEXT);
            CREATE INDEX IF NOT EXISTS ix_appr ON approvals(project_id);
            -- Idempotency for the scheduled sweeps (one morning brief per day, etc).
            CREATE TABLE IF NOT EXISTS sweep_log (
                project_id INTEGER, kind TEXT, day TEXT, ts TEXT,
                PRIMARY KEY (project_id, kind, day));
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

    def activities_on(self, project_id: int, date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM activity WHERE project_id=? AND substr(ts,1,10)=? ORDER BY id ASC",
                (project_id, date)).fetchall()]

    # ── media (ask-don't-analyse) ─────────────────────────────────────────
    def add_media(self, project_id: int, message_id: int, kind: str, path: str, filename: str,
                  sender_phone: str, sender_name: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO media (project_id, message_id, kind, path, filename,"
                            " sender_phone, sender_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (project_id, message_id, kind, path, filename, sender_phone,
                             sender_name, self._now()))
            return int(cur.lastrowid)

    def mark_media_asked(self, media_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE media SET asked=1 WHERE id=?", (media_id,))

    def awaiting_caption(self, project_id: int, phone: str) -> Optional[Dict[str, Any]]:
        """The most recent uncaptioned photo this person posted (we asked; they haven't said)."""
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM media WHERE project_id=? AND sender_phone=? AND asked=1"
                          " AND caption='' ORDER BY id DESC LIMIT 1",
                          (project_id, phone)).fetchone()
            return dict(r) if r else None

    def uncaptioned_media(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM media WHERE project_id=? AND caption='' AND asked=1"
                " ORDER BY id ASC", (project_id,)).fetchall()]

    def set_media_caption(self, media_id: int, caption: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE media SET caption=?, captioned_at=? WHERE id=?",
                      (caption[:500], self._now(), media_id))

    def bump_media_nudge(self, media_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE media SET nudges=nudges+1 WHERE id=?", (media_id,))

    def give_up_media(self, media_id: int) -> None:
        """Let it go (AllGud curiosity rule) — filed without context rather than nagging."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE media SET caption='(no context given)', captioned_at=? WHERE id=?",
                      (self._now(), media_id))

    def media_on(self, project_id: int, date: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM media WHERE project_id=? AND substr(created_at,1,10)=?"
                " ORDER BY id ASC", (project_id, date)).fetchall()]

    # ── the brain: durable memories ───────────────────────────────────────
    def add_memory(self, project_id: int, text: str, source: str, sender: str = "",
                   ref_date: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO memories (project_id, text, source, sender, ref_date, ts)"
                            " VALUES (?,?,?,?,?,?)",
                            (project_id, text[:1000], source, sender, ref_date, self._now()))
            return int(cur.lastrowid)

    def memories(self, project_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM memories WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (project_id, limit)).fetchall()]

    def memory_exists_for_date(self, project_id: int, source: str, ref_date: str) -> bool:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT 1 FROM memories WHERE project_id=? AND source=? AND ref_date=?",
                          (project_id, source, ref_date)).fetchone()
            return bool(r)

    # ── embeddings (semantic recall over messages + memories) ─────────────
    def save_embedding(self, project_id: int, ref_kind: str, ref_id: int, vec: bytes) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO embeddings (project_id, ref_kind, ref_id, vec)"
                      " VALUES (?,?,?,?)", (project_id, ref_kind, ref_id, vec))

    def all_embeddings(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT ref_kind, ref_id, vec FROM embeddings WHERE project_id=?",
                (project_id,)).fetchall()]

    def resolve_refs(self, project_id: int, refs: List[tuple]) -> List[Dict[str, Any]]:
        """[(ref_kind, ref_id)] → the underlying text rows, for grounding a recall answer."""
        out: List[Dict[str, Any]] = []
        msg_ids = [r for k, r in refs if k == "message"]
        mem_ids = [r for k, r in refs if k == "memory"]
        with self._lock, self._conn() as c:
            if msg_ids:
                ph = ",".join("?" for _ in msg_ids)
                for r in c.execute(f"SELECT id, sender_name, text, ts FROM messages WHERE id IN ({ph})",
                                   tuple(msg_ids)).fetchall():
                    out.append({"kind": "message", "who": r["sender_name"], "text": r["text"],
                                "ts": r["ts"]})
            if mem_ids:
                ph = ",".join("?" for _ in mem_ids)
                for r in c.execute(f"SELECT id, sender, text, ts, source FROM memories WHERE id IN ({ph})",
                                   tuple(mem_ids)).fetchall():
                    out.append({"kind": "memory", "who": r["sender"], "text": r["text"],
                                "ts": r["ts"], "source": r["source"]})
        out.sort(key=lambda x: x.get("ts", ""))
        return out

    # ── commitments (the promise ledger) ──────────────────────────────────
    def add_commitment(self, project_id: int, text: str, owner_name: str, owner_phone: str,
                       due_date: str, task_id: str = "", source_msg: int = 0) -> int:
        from datetime import date as _date
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO commitments (project_id, task_id, text, owner_name,"
                            " owner_phone, promised_on, due_date, source_msg)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (project_id, task_id, text[:300], owner_name, owner_phone,
                             _date.today().isoformat(), due_date, source_msg))
            return int(cur.lastrowid)

    def open_commitments(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM commitments WHERE project_id=? AND status='open' ORDER BY due_date",
                (project_id,)).fetchall()]

    def commitments_for(self, project_id: int, owner_name: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM commitments WHERE project_id=? AND status='open'"
                " AND lower(owner_name)=lower(?) ORDER BY due_date",
                (project_id, owner_name)).fetchall()]

    def close_commitments_for_task(self, project_id: int, task_id: str) -> int:
        """Task done → its promise is kept. Returns how many closed."""
        if not task_id:
            return 0
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE commitments SET status='kept', closed_on=? WHERE project_id=?"
                            " AND task_id=? AND status='open'",
                            (self._now(), project_id, task_id))
            return cur.rowcount

    def bump_commitment_nudge(self, cid: int, day: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE commitments SET nudges=nudges+1, last_nudge=? WHERE id=?", (day, cid))

    def set_commitment_due(self, cid: int, due: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE commitments SET due_date=?, nudges=0 WHERE id=?", (due, cid))

    # ── approvals (the evidence trail) ────────────────────────────────────
    def add_approval(self, project_id: int, text: str, approver_name: str, approver_phone: str,
                     source_msg: int = 0, media_ref: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO approvals (project_id, text, approver_name,"
                            " approver_phone, source_msg, media_ref, approved_on)"
                            " VALUES (?,?,?,?,?,?,?)",
                            (project_id, text[:400], approver_name, approver_phone,
                             source_msg, media_ref, self._now()))
            return int(cur.lastrowid)

    def approvals(self, project_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM approvals WHERE project_id=? ORDER BY id ASC",
                (project_id,)).fetchall()]

    # ── sweep idempotency ─────────────────────────────────────────────────
    def sweep_done(self, project_id: int, kind: str, day: str) -> bool:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT 1 FROM sweep_log WHERE project_id=? AND kind=? AND day=?",
                          (project_id, kind, day)).fetchone()
            return bool(r)

    def mark_sweep(self, project_id: int, kind: str, day: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO sweep_log (project_id, kind, day, ts)"
                      " VALUES (?,?,?,?)", (project_id, kind, day, self._now()))

    def keyword_search(self, project_id: int, terms: List[str], limit: int = 8) -> List[Dict[str, Any]]:
        """Fallback when embeddings aren't configured — recall degrades, never breaks."""
        if not terms:
            return []
        cl = " OR ".join("text LIKE ?" for _ in terms)
        args: List[Any] = [f"%{t}%" for t in terms]
        out: List[Dict[str, Any]] = []
        with self._lock, self._conn() as c:
            for r in c.execute(f"SELECT sender_name who, text, ts FROM messages WHERE project_id=?"
                               f" AND ({cl}) ORDER BY id DESC LIMIT ?",
                               (project_id, *args, limit)).fetchall():
                out.append({"kind": "message", **dict(r)})
            for r in c.execute(f"SELECT sender who, text, ts FROM memories WHERE project_id=?"
                               f" AND ({cl}) ORDER BY id DESC LIMIT ?",
                               (project_id, *args, limit)).fetchall():
                out.append({"kind": "memory", **dict(r)})
        out.sort(key=lambda x: x.get("ts", ""))
        return out[:limit]
