"""
Conversation memory that survives restarts.

  ops_turns     every message in each person's thread (theirs and ARVIS's)
  ops_notices   what ARVIS already told whom about which topic — so it never
                announces the same fault twice, and knows what a person knows
  ops_inbound   inbound message ids already handled (the channel retries webhooks)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_DDL = (
    """CREATE TABLE IF NOT EXISTS ops_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, speaker TEXT NOT NULL,
        text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'chat', meta TEXT, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_turns_number ON ops_turns(number, id)",
    """CREATE TABLE IF NOT EXISTS ops_notices (
        number TEXT NOT NULL, topic TEXT NOT NULL, sent_at TEXT NOT NULL, summary TEXT,
        PRIMARY KEY (number, topic))""",
    "CREATE TABLE IF NOT EXISTS ops_inbound (message_id TEXT PRIMARY KEY, received_at TEXT)",
    # ARVIS's own WhatsApp identities (phone jid, and the @lid it is mentioned by in groups).
    "CREATE TABLE IF NOT EXISTS ops_identity (jid TEXT PRIMARY KEY, learned_at TEXT)",
)


@dataclass
class Turn:
    speaker: str        # "person" | "arvis"
    text: str
    kind: str           # chat | proactive | check
    created_at: str


class ConversationStore:
    def __init__(self, database: Any, clock=None):
        self.database = database
        # One notion of "now" for everything that reads these timestamps (gate, situation).
        # Naive local wall-clock by default; injectable so behaviour over time can be replayed.
        self.clock = clock or datetime.now

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    async def append(self, number: str, speaker: str, text: str, kind: str = "chat",
                     meta: Optional[Dict[str, Any]] = None) -> None:
        conn = await self._conn()
        await conn.execute("INSERT INTO ops_turns (number, speaker, text, kind, meta, created_at) VALUES (?,?,?,?,?,?)",
                           (number, speaker, text, kind, json.dumps(meta or {}, default=str), self._now()))
        await conn.commit()

    async def recent(self, number: str, limit: int = 12, max_age_h: float = 72.0) -> List[Turn]:
        """The last turns of this person's thread, oldest first. Old turns age out:
        a conversation from last week is not context for this morning."""
        cutoff = (self.clock() - timedelta(hours=max_age_h)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute(
                "SELECT speaker, text, kind, created_at FROM ops_turns WHERE number = ? AND created_at >= ? "
                "ORDER BY id DESC LIMIT ?", (number, cutoff, limit)) as cur:
            rows = await cur.fetchall()
        return [Turn(*r) for r in reversed(rows)]

    async def arvis_message(self, number: str, message_id: str) -> Optional[Dict[str, Any]]:
        """ARVIS's own message with this WhatsApp id in this thread (its meta), if it is one."""
        if not message_id:
            return None
        conn = await self._conn()
        async with conn.execute(
                "SELECT meta FROM ops_turns WHERE number = ? AND speaker = 'arvis' "
                "AND json_extract(meta, '$.message_id') = ? ORDER BY id DESC LIMIT 1", (number, message_id)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0] or "{}") if row else None

    async def own_ids(self) -> set:
        conn = await self._conn()
        async with conn.execute("SELECT jid FROM ops_identity") as cur:
            return {r[0] for r in await cur.fetchall()}

    async def add_own_id(self, jid: str) -> None:
        conn = await self._conn()
        await conn.execute("INSERT OR IGNORE INTO ops_identity (jid, learned_at) VALUES (?, ?)", (jid, self._now()))
        await conn.commit()

    async def first_time(self, message_id: str) -> bool:
        conn = await self._conn()
        cur = await conn.execute("INSERT OR IGNORE INTO ops_inbound (message_id, received_at) VALUES (?, ?)",
                                 (message_id, self._now()))
        await conn.commit()
        return cur.rowcount == 1

    async def told(self, number: str, topic: str) -> bool:
        conn = await self._conn()
        async with conn.execute("SELECT 1 FROM ops_notices WHERE number = ? AND topic = ?", (number, topic)) as cur:
            return await cur.fetchone() is not None

    async def mark_told(self, number: str, topic: str, summary: str = "") -> None:
        conn = await self._conn()
        await conn.execute("INSERT OR REPLACE INTO ops_notices (number, topic, sent_at, summary) VALUES (?,?,?,?)",
                           (number, topic, self._now(), summary[:300]))
        await conn.commit()

    async def forget_topic(self, topic: str) -> None:
        """A fault cleared: if it comes back, it is news again."""
        conn = await self._conn()
        await conn.execute("DELETE FROM ops_notices WHERE topic = ?", (topic,))
        await conn.commit()

    async def notices_since(self, number: str, hours: float) -> List[Dict[str, str]]:
        cutoff = (self.clock() - timedelta(hours=hours)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT topic, sent_at, summary FROM ops_notices WHERE number = ? AND sent_at >= ? "
                                "ORDER BY sent_at", (number, cutoff)) as cur:
            return [{"topic": r[0], "sent_at": r[1], "summary": r[2]} for r in await cur.fetchall()]

    async def proactive_count(self, number: str, hours: float = 1.0) -> int:
        cutoff = (self.clock() - timedelta(hours=hours)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT COUNT(*) FROM ops_turns WHERE number = ? AND speaker = 'arvis' "
                                "AND kind = 'proactive' AND created_at >= ?", (number, cutoff)) as cur:
            return int((await cur.fetchone())[0])
