"""
ARVIS learns the building and its people — explainably.

  Engagement   every unprompted message gets an outcome from how the person reacted:
               acted (asked a technician, logged a repair, asked about it), acked
               ("on it"), dismissed ("I know", "not important", "stop"), or ignored (no
               reply within ARVIS_OPS_REACTION_H, 4 h). Per person and kind of signal:
                   p = (1 + engaged) / (2 + engaged + ignored + 2·dismissed)
               over 60 days; with ≥5 outcomes and p < 0.25 that kind goes one level
               quieter FOR THAT PERSON (never below the brief, never for safety).
  Preferences  what people say: "don't message me about VAVs unless it's critical",
               "energy faults in the morning brief only" — stored, confirmed back.
  Normals      the same thing dismissed ≥3 times in 30 days at the same kind of day and
               hour → "that's normal for this building": no more interruptions, announced
               once in the brief, undone with one sentence. Never for safety.
  Facts        "AHU-07 serves level 3 west" → ARVIS reads it back, saves it only on
               "yes", with who said it and when; used in every conversation and
               investigation after that.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_DDL = (
    """CREATE TABLE IF NOT EXISTS ops_engagement (
        id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, topic TEXT, kind TEXT, subject TEXT,
        message_id TEXT, sent_at TEXT, day_type TEXT, hour INT,
        reaction TEXT NOT NULL DEFAULT 'pending', reacted_at TEXT, evidence TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_engagement ON ops_engagement(number, kind, reaction)",
    """CREATE TABLE IF NOT EXISTS ops_prefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, scope_kind TEXT, scope_value TEXT, mode TEXT,
        until TEXT, said TEXT, created_at TEXT, active INT DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS ops_normals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, subject TEXT, day_type TEXT, hour_from INT,
        hour_to INT, evidence TEXT, status TEXT DEFAULT 'active', created_at TEXT, announced_at TEXT,
        revoked_by TEXT)""",
    """CREATE TABLE IF NOT EXISTS building_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, statement TEXT NOT NULL,
        said_by_number TEXT, said_by_name TEXT, said_at TEXT, confirmed_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending', superseded_by INT)""",
)

# Friendly scopes the engineer can pass → signal kinds
KIND_SCOPES = {
    "fault": ("fdd_fault",), "repair": ("fdd_fix",), "alarm": ("alarm",), "investigation": ("investigation",),
    "advisory": ("advisory",), "drift": ("drift",), "monitoring": ("monitoring",), "check": ("field_check",),
}
_DISMISS = re.compile(r"\b(i\s*know|already\s*know|not\s*important|don'?t\s*care|stop|ignore|not\s*now|"
                      r"no\s*need|nothing\s*to\s*worry|it'?s\s*normal|that'?s\s*normal|known\s*issue)\b"
                      r"|معروف|عادي|مو\s*مهم|ليس\s*مهم", re.IGNORECASE)
_ACTING_TOOLS = {"ask_technician", "record_repair", "equipment_status", "point_history", "change_since",
                 "alarm_changes", "open_cases", "deep_investigation", "acknowledge"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[-_\s]", "", (s or "").upper())


@dataclass
class Fact:
    id: int
    subject: Optional[str]
    statement: str
    said_by_name: str
    said_at: str
    status: str


class Learning:
    def __init__(self, database: Any, clock=None):
        self.database = database
        self.clock = clock or datetime.now            # same naive-local clock as the conversation store
        self.window_h = _env_float("ARVIS_OPS_REACTION_H", 4.0)

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    # ── engagement ────────────────────────────────────────────────────────
    async def record_delivery(self, number: str, topic: str, kind: str, subject: Optional[str],
                              message_id: Optional[str], day_type: str, hour: int) -> None:
        conn = await self._conn()
        await conn.execute("INSERT INTO ops_engagement (number, topic, kind, subject, message_id, sent_at, "
                           "day_type, hour) VALUES (?,?,?,?,?,?,?,?)",
                           (number, topic, kind, subject, message_id, self._now(), day_type, hour))
        await conn.commit()

    async def observe(self, number: str, text: str, reply_to: Optional[str] = None,
                      tools: Optional[List[Dict[str, Any]]] = None, ack: bool = False) -> Optional[str]:
        """Attribute an inbound message to the delivery it reacts to. Returns the reaction."""
        await self.sweep()
        cutoff = (self.clock() - timedelta(hours=self.window_h)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT id, subject, message_id FROM ops_engagement WHERE number=? AND "
                                "reaction='pending' AND sent_at >= ? ORDER BY id DESC", (number, cutoff)) as cur:
            pending = [{"id": r[0], "subject": r[1], "message_id": r[2]} for r in await cur.fetchall()]
        if not pending:
            return None
        tools = tools or []
        tool_subjects = {_norm(str(v)) for t in tools for k, v in (t.get("args") or {}).items()
                         if k in ("equipment_id", "subject", "point_id") and v}
        target = next((p for p in pending if reply_to and p["message_id"] == reply_to), None)
        if target is None:
            target = next((p for p in pending if p["subject"] and (
                _norm(p["subject"]) in _norm(text) or any(_norm(p["subject"]) in s for s in tool_subjects))), None)
        if target is None and len(pending) == 1:
            target = pending[0]
        if target is None:
            return None
        if ack:
            reaction = "acked"
        elif _DISMISS.search(text or ""):
            reaction = "dismissed"
        elif any(t.get("name") in _ACTING_TOOLS for t in tools) or "?" in (text or ""):
            reaction = "acted"
        else:
            reaction = "replied"
        await conn.execute("UPDATE ops_engagement SET reaction=?, reacted_at=?, evidence=? WHERE id=?",
                           (reaction, self._now(), (text or "")[:300], target["id"]))
        await conn.commit()
        return reaction

    async def sweep(self) -> int:
        """Deliveries nobody reacted to within the window → ignored."""
        cutoff = (self.clock() - timedelta(hours=self.window_h)).isoformat(timespec="seconds")
        conn = await self._conn()
        cur = await conn.execute("UPDATE ops_engagement SET reaction='ignored', reacted_at=? "
                                 "WHERE reaction='pending' AND sent_at < ?", (self._now(), cutoff))
        await conn.commit()
        return cur.rowcount

    async def engagement(self, number: str, kind: str, days: float = 60.0) -> Dict[str, Any]:
        cutoff = (self.clock() - timedelta(days=days)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT reaction, COUNT(*) FROM ops_engagement WHERE number=? AND kind=? "
                                "AND sent_at >= ? AND reaction != 'pending' GROUP BY reaction",
                                (number, kind, cutoff)) as cur:
            counts = {r[0]: r[1] for r in await cur.fetchall()}
        engaged = counts.get("acted", 0) + counts.get("acked", 0) + counts.get("replied", 0)
        ignored, dismissed = counts.get("ignored", 0), counts.get("dismissed", 0)
        n = engaged + ignored + dismissed
        return {"n": n, "engaged": engaged, "ignored": ignored, "dismissed": dismissed,
                "p": (1 + engaged) / (2 + engaged + ignored + 2 * dismissed)}

    # ── preferences ───────────────────────────────────────────────────────
    async def set_preference(self, number: str, scope_kind: str, scope_value: str, mode: str,
                             said: str = "", until_hours: Optional[float] = None) -> int:
        if mode not in ("mute", "digest", "normal"):
            raise ValueError("mode must be mute, digest or normal")
        if scope_kind not in ("all", "equipment") and scope_kind not in KIND_SCOPES:
            raise ValueError(f"scope must be all, equipment or one of {', '.join(KIND_SCOPES)}")
        conn = await self._conn()
        await conn.execute("UPDATE ops_prefs SET active=0 WHERE number=? AND scope_kind=? AND scope_value=?",
                           (number, scope_kind, scope_value or ""))
        until = (self.clock() + timedelta(hours=until_hours)).isoformat(timespec="seconds") if until_hours else None
        cur = await conn.execute("INSERT INTO ops_prefs (number, scope_kind, scope_value, mode, until, said, "
                                 "created_at) VALUES (?,?,?,?,?,?,?)",
                                 (number, scope_kind, scope_value or "", mode, until, said[:300], self._now()))
        await conn.commit()
        return cur.lastrowid

    async def preferences(self, number: str) -> List[Dict[str, Any]]:
        conn = await self._conn()
        async with conn.execute("SELECT id, scope_kind, scope_value, mode, until, said FROM ops_prefs "
                                "WHERE number=? AND active=1 AND mode != 'normal' AND "
                                "(until IS NULL OR until > ?)", (number, self._now())) as cur:
            return [{"id": r[0], "scope_kind": r[1], "scope_value": r[2], "mode": r[3], "until": r[4],
                     "said": r[5]} for r in await cur.fetchall()]

    async def preference_for(self, number: str, kind: str, subject: Optional[str]) -> Optional[Dict[str, Any]]:
        """The strictest active preference that applies to this kind of signal / equipment."""
        best = None
        for p in await self.preferences(number):
            applies = (p["scope_kind"] == "all"
                       or (p["scope_kind"] == "equipment" and subject and _norm(p["scope_value"]) in _norm(subject))
                       or kind in KIND_SCOPES.get(p["scope_kind"], ()))
            if applies and (best is None or p["mode"] == "mute"):
                best = p
        return best

    # ── normals ───────────────────────────────────────────────────────────
    async def learn_normals(self, min_dismissals: int = 3, days: float = 30.0) -> List[Dict[str, Any]]:
        """Recurring dismissals at the same kind of day and hour → learned normal."""
        cutoff = (self.clock() - timedelta(days=days)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT kind, subject, day_type, hour, id FROM ops_engagement "
                                "WHERE reaction='dismissed' AND sent_at >= ? AND kind NOT IN "
                                "('monitoring','field_check') AND subject IS NOT NULL", (cutoff,)) as cur:
            rows = await cur.fetchall()
        groups: Dict[tuple, List] = {}
        for kind, subject, day_type, hour, eid in rows:
            groups.setdefault((kind, subject, day_type), []).append((hour, eid))
        created = []
        for (kind, subject, day_type), items in groups.items():
            hours = sorted(h for h, _ in items)
            for h in hours:                                        # a ±1 h cluster with enough dismissals
                cluster = [(x, e) for x, e in items if abs(x - h) <= 1]
                if len(cluster) < min_dismissals:
                    continue
                lo, hi = min(x for x, _ in cluster), max(x for x, _ in cluster) + 1
                async with conn.execute("SELECT 1 FROM ops_normals WHERE kind=? AND subject=? AND day_type=? "
                                        "AND status='active' AND hour_from<=? AND hour_to>=?",
                                        (kind, subject, day_type, h, h + 1)) as cur:
                    if await cur.fetchone():
                        break
                cur = await conn.execute("INSERT INTO ops_normals (kind, subject, day_type, hour_from, hour_to, "
                                         "evidence, created_at) VALUES (?,?,?,?,?,?,?)",
                                         (kind, subject, day_type, lo, hi, json.dumps([e for _, e in cluster]),
                                          self._now()))
                created.append({"id": cur.lastrowid, "kind": kind, "subject": subject, "day_type": day_type,
                                "hours": f"{lo:02d}:00-{hi:02d}:00", "dismissals": len(cluster)})
                break
        await conn.commit()
        return created

    async def normal_for(self, kind: str, subject: Optional[str], day_type: str, hour: int) -> Optional[Dict]:
        if not subject:
            return None
        conn = await self._conn()
        async with conn.execute("SELECT id, hour_from, hour_to FROM ops_normals WHERE kind=? AND subject=? AND "
                                "day_type=? AND status='active' AND hour_from<=? AND hour_to>?",
                                (kind, subject, day_type, hour, hour)) as cur:
            r = await cur.fetchone()
        return {"id": r[0], "hours": f"{r[1]:02d}:00-{r[2]:02d}:00"} if r else None

    async def unannounced_normals(self) -> List[Dict[str, Any]]:
        conn = await self._conn()
        async with conn.execute("SELECT id, kind, subject, day_type, hour_from, hour_to FROM ops_normals "
                                "WHERE status='active' AND announced_at IS NULL") as cur:
            return [{"id": r[0], "kind": r[1], "subject": r[2], "day_type": r[3],
                     "hours": f"{r[4]:02d}:00-{r[5]:02d}:00"} for r in await cur.fetchall()]

    async def mark_announced(self, ids: List[int]) -> None:
        if ids:
            conn = await self._conn()
            await conn.execute(f"UPDATE ops_normals SET announced_at=? WHERE id IN ({','.join('?' * len(ids))})",
                               (self._now(), *ids))
            await conn.commit()

    async def revoke_normal(self, subject: str, by: str) -> int:
        conn = await self._conn()
        cur = await conn.execute("UPDATE ops_normals SET status='revoked', revoked_by=? WHERE status='active' "
                                 "AND REPLACE(REPLACE(UPPER(subject),'-',''),' ','') = ?", (by, _norm(subject)))
        await conn.commit()
        return cur.rowcount

    # ── facts ─────────────────────────────────────────────────────────────
    async def propose_fact(self, subject: Optional[str], statement: str, number: str, name: str) -> int:
        conn = await self._conn()
        await conn.execute("UPDATE building_facts SET status='expired' WHERE said_by_number=? AND status='pending'",
                           (number,))
        cur = await conn.execute("INSERT INTO building_facts (subject, statement, said_by_number, said_by_name, "
                                 "said_at, status) VALUES (?,?,?,?,?,'pending')",
                                 (subject, statement.strip()[:500], number, name, self._now()))
        await conn.commit()
        return cur.lastrowid

    async def pending_fact(self, number: str, within_hours: float = 24.0) -> Optional[Fact]:
        cutoff = (self.clock() - timedelta(hours=within_hours)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT id, subject, statement, said_by_name, said_at, status FROM building_facts "
                                "WHERE said_by_number=? AND status='pending' AND said_at >= ? ORDER BY id DESC "
                                "LIMIT 1", (number, cutoff)) as cur:
            r = await cur.fetchone()
        return Fact(*r) if r else None

    async def settle_fact(self, fact_id: int, confirmed: bool) -> Optional[Fact]:
        conn = await self._conn()
        if confirmed:
            async with conn.execute("SELECT subject FROM building_facts WHERE id=?", (fact_id,)) as cur:
                row = await cur.fetchone()
            if row and row[0]:                                  # a newer fact about the same thing supersedes
                await conn.execute("UPDATE building_facts SET status='superseded', superseded_by=? WHERE "
                                   "status='active' AND subject=? AND id != ?", (fact_id, row[0], fact_id))
            await conn.execute("UPDATE building_facts SET status='active', confirmed_at=? WHERE id=?",
                               (self._now(), fact_id))
        else:
            await conn.execute("UPDATE building_facts SET status='rejected' WHERE id=?", (fact_id,))
        await conn.commit()
        async with conn.execute("SELECT id, subject, statement, said_by_name, said_at, status FROM building_facts "
                                "WHERE id=?", (fact_id,)) as cur:
            r = await cur.fetchone()
        return Fact(*r) if r else None

    async def facts(self, subjects: Optional[List[str]] = None, limit: int = 12) -> List[Fact]:
        conn = await self._conn()
        async with conn.execute("SELECT id, subject, statement, said_by_name, said_at, status FROM building_facts "
                                "WHERE status='active' ORDER BY id DESC") as cur:
            rows = [Fact(*r) for r in await cur.fetchall()]
        if subjects:
            want = {_norm(s) for s in subjects}
            focused = [f for f in rows if f.subject and _norm(f.subject) in want]
            general = [f for f in rows if not f.subject]
            rows = focused + general
        return rows[:limit]
