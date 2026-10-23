"""
The attention gate's durable record.

  ops_signals    every signal topic seen, its state (open / acknowledged / resolved)
                 and its escalation ladder position
  ops_decisions  every decision for every person, with the reasons — so ARVIS can
                 answer "why didn't you tell me?" and the thresholds can be tuned
  ops_queue      things held for later (SOON, or DIGEST for the next brief) — held
                 means queued, never silently dropped
  ops_alerts     NOW messages awaiting acknowledgement

Times are UTC ISO strings with offset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_commercial.ops_engineer.signals import Signal

_DDL = (
    """CREATE TABLE IF NOT EXISTS ops_signals (
        topic TEXT PRIMARY KEY, kind TEXT, subject TEXT, severity TEXT, safety INT, llm_origin INT,
        title TEXT, facts TEXT, ref TEXT, state TEXT NOT NULL DEFAULT 'open',
        ack_by TEXT, ack_at TEXT, resolved_at TEXT, first_seen TEXT, last_seen TEXT,
        occurrences INT DEFAULT 1, ladder_level INT DEFAULT -1, next_escalation_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS ops_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, subject TEXT, number TEXT, level TEXT,
        reasons TEXT, decided_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_decisions_subject ON ops_decisions(subject, decided_at)",
    """CREATE TABLE IF NOT EXISTS ops_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, number TEXT, level TEXT, kind TEXT,
        title TEXT, facts TEXT, due_at TEXT, status TEXT NOT NULL DEFAULT 'pending',
        attempts INT DEFAULT 0, created_at TEXT, sent_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_queue_due ON ops_queue(status, due_at)",
    """CREATE TABLE IF NOT EXISTS ops_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, number TEXT, message_id TEXT,
        sent_at TEXT, acked_at TEXT)""",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.astimezone()).astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class QueueItem:
    id: int
    topic: str
    number: str
    level: str
    kind: str
    title: str
    facts: str
    due_at: str
    attempts: int


class SignalLedger:
    def __init__(self, database: Any):
        self.database = database

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    # ── signals ───────────────────────────────────────────────────────────
    async def upsert(self, s: Signal, now: datetime) -> Dict[str, Any]:
        """Record a signal; returns its row (state, occurrences, previous severity)."""
        conn = await self._conn()
        prev = await self.get(s.topic)
        if prev is None:
            await conn.execute(
                "INSERT INTO ops_signals (topic, kind, subject, severity, safety, llm_origin, title, facts, ref, "
                "state, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)",
                (s.topic, s.kind, s.subject, s.severity, int(s.safety), int(s.llm_origin), s.title, s.facts,
                 json.dumps(s.ref, default=str), iso(now), iso(now)))
        else:
            reopened = prev["state"] == "resolved"
            await conn.execute(
                "UPDATE ops_signals SET severity=?, facts=?, title=?, last_seen=?, occurrences=occurrences+1, "
                "state=CASE WHEN ? THEN 'open' ELSE state END, "
                "resolved_at=CASE WHEN ? THEN NULL ELSE resolved_at END WHERE topic=?",
                (s.severity, s.facts, s.title, iso(now), int(reopened), int(reopened), s.topic))
        await conn.commit()
        return {"previous": prev, "current": await self.get(s.topic)}

    async def get(self, topic: str) -> Optional[Dict[str, Any]]:
        conn = await self._conn()
        async with conn.execute("SELECT topic, kind, subject, severity, safety, llm_origin, title, facts, ref, "
                                "state, ack_by, ack_at, resolved_at, ladder_level, next_escalation_at, "
                                "occurrences FROM ops_signals WHERE topic=?", (topic,)) as cur:
            r = await cur.fetchone()
        if r is None:
            return None
        keys = ("topic", "kind", "subject", "severity", "safety", "llm_origin", "title", "facts", "ref", "state",
                "ack_by", "ack_at", "resolved_at", "ladder_level", "next_escalation_at", "occurrences")
        row = dict(zip(keys, r))
        row["ref"] = json.loads(row["ref"] or "{}")
        return row

    async def open_on(self, subject: str, kinds: tuple) -> List[Dict[str, Any]]:
        """Open signals of these kinds on a subject (corroboration for LLM-origin signals)."""
        if not subject:
            return []
        conn = await self._conn()
        ph = ",".join("?" * len(kinds))
        async with conn.execute(f"SELECT topic FROM ops_signals WHERE subject=? AND state='open' AND kind IN ({ph})",
                                (subject, *kinds)) as cur:
            return [{"topic": r[0]} for r in await cur.fetchall()]

    async def resolve(self, topic: str, now: datetime) -> bool:
        conn = await self._conn()
        cur = await conn.execute("UPDATE ops_signals SET state='resolved', resolved_at=?, next_escalation_at=NULL "
                                 "WHERE topic=? AND state!='resolved'", (iso(now), topic))
        await conn.execute("UPDATE ops_queue SET status='cancelled' WHERE topic=? AND status='pending'", (topic,))
        await conn.commit()
        return cur.rowcount > 0

    async def acknowledge(self, topic: str, by: str, now: datetime) -> bool:
        conn = await self._conn()
        cur = await conn.execute("UPDATE ops_signals SET state='acknowledged', ack_by=?, ack_at=?, "
                                 "next_escalation_at=NULL WHERE topic=? AND state='open'", (by, iso(now), topic))
        await conn.execute("UPDATE ops_alerts SET acked_at=? WHERE topic=? AND acked_at IS NULL", (iso(now), topic))
        await conn.commit()
        return cur.rowcount > 0

    async def set_ladder(self, topic: str, level: int, next_at: Optional[datetime]) -> None:
        conn = await self._conn()
        await conn.execute("UPDATE ops_signals SET ladder_level=?, next_escalation_at=? WHERE topic=?",
                           (level, iso(next_at) if next_at else None, topic))
        await conn.commit()

    async def ladder_due(self, now: datetime) -> List[Dict[str, Any]]:
        conn = await self._conn()
        async with conn.execute("SELECT topic FROM ops_signals WHERE state='open' AND next_escalation_at IS NOT NULL "
                                "AND next_escalation_at <= ?", (iso(now),)) as cur:
            topics = [r[0] for r in await cur.fetchall()]
        return [await self.get(t) for t in topics]

    # ── decisions ─────────────────────────────────────────────────────────
    async def record_decision(self, s: Signal, number: str, level: str, reasons: List[Dict[str, str]],
                              now: datetime) -> None:
        conn = await self._conn()
        await conn.execute("INSERT INTO ops_decisions (topic, subject, number, level, reasons, decided_at) "
                           "VALUES (?,?,?,?,?,?)", (s.topic, s.subject, number, level, json.dumps(reasons), iso(now)))
        await conn.commit()

    async def decisions_about(self, needle: str, number: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Recent decisions on a subject or topic (for 'why didn't you tell me about X?')."""
        conn = await self._conn()
        q = ("SELECT topic, subject, number, level, reasons, decided_at FROM ops_decisions "
             "WHERE (subject LIKE ? OR topic LIKE ?)")
        args: list = [f"%{needle}%", f"%{needle}%"]
        if number:
            q += " AND number=?"
            args.append(number)
        async with conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)) as cur:
            return [{"topic": r[0], "subject": r[1], "number": r[2], "level": r[3],
                     "reasons": json.loads(r[4] or "[]"), "decided_at": r[5]} for r in await cur.fetchall()]

    # ── queue ─────────────────────────────────────────────────────────────
    async def enqueue(self, s: Signal, number: str, level: str, due: datetime, now: datetime) -> None:
        conn = await self._conn()
        async with conn.execute("SELECT id FROM ops_queue WHERE topic=? AND number=? AND status='pending'",
                                (s.topic, number)) as cur:
            existing = await cur.fetchone()
        if existing:                                   # same thing already waiting: refresh, don't duplicate
            await conn.execute("UPDATE ops_queue SET facts=?, title=?, level=?, "
                               "due_at=MIN(due_at, ?) WHERE id=?", (s.facts, s.title, level, iso(due), existing[0]))
        else:
            await conn.execute("INSERT INTO ops_queue (topic, number, level, kind, title, facts, due_at, created_at) "
                               "VALUES (?,?,?,?,?,?,?,?)",
                               (s.topic, number, level, s.kind, s.title, s.facts, iso(due), iso(now)))
        await conn.commit()

    async def due(self, now: datetime, level: Optional[str] = None,
                  number: Optional[str] = None) -> List[QueueItem]:
        conn = await self._conn()
        q, args = "SELECT id, topic, number, level, kind, title, facts, due_at, attempts FROM ops_queue " \
                  "WHERE status='pending' AND due_at <= ?", [iso(now)]
        if level:
            q, args = q + " AND level=?", args + [level]
        if number:
            q, args = q + " AND number=?", args + [number]
        async with conn.execute(q + " ORDER BY due_at, id", args) as cur:
            return [QueueItem(*r) for r in await cur.fetchall()]

    async def pending_for(self, number: str) -> List[QueueItem]:
        conn = await self._conn()
        async with conn.execute("SELECT id, topic, number, level, kind, title, facts, due_at, attempts FROM ops_queue "
                                "WHERE status='pending' AND number=? ORDER BY due_at, id", (number,)) as cur:
            return [QueueItem(*r) for r in await cur.fetchall()]

    async def mark(self, ids: List[int], status: str, now: datetime) -> None:
        if not ids:
            return
        conn = await self._conn()
        ph = ",".join("?" * len(ids))
        if status == "retry":
            await conn.execute(f"UPDATE ops_queue SET attempts=attempts+1 WHERE id IN ({ph})", ids)
        else:
            await conn.execute(f"UPDATE ops_queue SET status=?, sent_at=? WHERE id IN ({ph})",
                               (status, iso(now), *ids))
        await conn.commit()

    # ── alerts awaiting acknowledgement ───────────────────────────────────
    async def add_alert(self, topic: str, number: str, message_id: Optional[str], now: datetime) -> None:
        conn = await self._conn()
        await conn.execute("INSERT INTO ops_alerts (topic, number, message_id, sent_at) VALUES (?,?,?,?)",
                           (topic, number, message_id, iso(now)))
        await conn.commit()

    async def open_alerts(self, number: str, within_hours: float = 12.0) -> List[Dict[str, Any]]:
        """NOW alerts sent to this person, not yet acknowledged, whose signal is still open."""
        from datetime import timedelta
        cutoff = iso(utcnow() - timedelta(hours=within_hours))
        conn = await self._conn()
        async with conn.execute(
                "SELECT a.topic, a.message_id, a.sent_at, s.title, s.ref FROM ops_alerts a "
                "JOIN ops_signals s ON s.topic = a.topic WHERE a.number=? AND a.acked_at IS NULL "
                "AND s.state='open' AND a.sent_at >= ? ORDER BY a.id DESC", (number, cutoff)) as cur:
            return [{"topic": r[0], "message_id": r[1], "sent_at": r[2], "title": r[3],
                     "ref": json.loads(r[4] or "{}")} for r in await cur.fetchall()]
