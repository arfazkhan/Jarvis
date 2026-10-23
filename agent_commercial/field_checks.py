"""
Field checks — technicians as sensors
=====================================

Where the BMS cannot tell two causes apart, ARVIS asks the technician on site
the ONE question that separates them best (the diagnosis case's
``next_question``, chosen by expected information gain), over a messaging
channel such as WhatsApp. The answer goes into the same diagnosis the API
uses (``answer_question``), the causes re-rank, and ARVIS either reports the
most likely cause or asks the next most useful question.

    case.next_question ──► technician ──► YES / NO / NOT SURE ──► answer_question
          ▲                                                           │
          └──────────── next question (bounded) ◄── re-ranked causes ◄┘

Rules:
  * Only technicians on the roster are listened to, and only about their own
    checks. Anyone else is ignored (logged once).
  * "Not sure" is never turned into a yes or no: the check is closed as
    unsure and the case is left for an engineer.
  * Read-only towards the building: an answer changes the diagnosis, never
    equipment. Messages carry no command path.
  * A question is asked at most once per case per chain, and a chain stops
    after ARVIS_FIELD_CHECK_MAX_CHAIN questions (default 4).

The transport is pluggable (agent_commercial/messaging/evolution.py — WhatsApp
through a self-hosted Evolution API). It needs ``send_check(to, body, ref) ->
message_id`` and ``send_text(to, body) -> message_id``. Inbound message ids are
de-duplicated here, because the channel retries webhooks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger("arvis.field_checks")

_DDL = """CREATE TABLE IF NOT EXISTS field_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL, equipment_id TEXT NOT NULL, rule_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL, question TEXT NOT NULL,
    technician TEXT NOT NULL, technician_name TEXT,
    status TEXT NOT NULL DEFAULT 'sent',     -- sent | answered | unsure | expired | failed
    answer TEXT, message_id TEXT, chain INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, answered_at TEXT, error TEXT)"""
_IDX = ("CREATE INDEX IF NOT EXISTS idx_field_checks_tech ON field_checks(technician, status)",
        "CREATE INDEX IF NOT EXISTS idx_field_checks_msg ON field_checks(message_id)",
        # inbound message ids already handled — webhooks are retried, answers must apply once
        "CREATE TABLE IF NOT EXISTS field_check_inbound (message_id TEXT PRIMARY KEY, received_at TEXT)")

_REF = re.compile(r"\bC\s?(\d{1,7})\b", re.IGNORECASE)
# Order matters: "لا أعرف" (don't know) contains "لا" (no).
_UNSURE = re.compile(r"\b(not\s*sure|unsure|don'?t\s*know|dont\s*know|no\s*idea|maybe|can'?t\s*tell|n/?a)\b"
                     r"|مش\s*متأكد|لست\s*متأكد|غير\s*متأكد|لا\s*أعرف|لا\s*اعرف|ما\s*ادري|ما\s*أدري", re.IGNORECASE)
_YES = re.compile(r"^\s*(yes|y|yeah|yep|yup|correct|confirmed|true|ok\s*yes)\b|^\s*(نعم|ايوه|أيوه|ايوا|أيوا|اي|إي|اكيد|أكيد)",
                  re.IGNORECASE)
_NO = re.compile(r"^\s*(no|n|nope|negative|false|not\s+really)\b|^\s*(لا|لأ|كلا)(\s|$|[.!،,])", re.IGNORECASE)


def normalize_number(raw: str) -> str:
    """'+974 5550-1234' → '97455501234' (WhatsApp wa_id form)."""
    return re.sub(r"\D", "", raw or "")


def parse_answer(text: str) -> Optional[str]:
    """'yes' | 'no' | 'unsure' | None (could not tell — ask again, never guess)."""
    t = _REF.sub(" ", text or "").strip()
    if not t:
        return None
    if _UNSURE.search(t):
        return "unsure"
    if _YES.search(t):
        return "yes"
    if _NO.search(t):
        return "no"
    return None


def load_roster(raw: Optional[str] = None) -> Dict[str, str]:
    """ARVIS_FIELD_TECHNICIANS="Ali:+97455501234, Ravi:+97455505678" → {number: name}."""
    raw = os.getenv("ARVIS_FIELD_TECHNICIANS", "") if raw is None else raw
    roster: Dict[str, str] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        name, number = part.rsplit(":", 1)
        n = normalize_number(number)
        if n:
            roster[n] = name.strip() or n
    return roster


class Transport(Protocol):
    async def send_check(self, to: str, body: str, ref: str) -> str: ...
    async def send_text(self, to: str, body: str) -> str: ...


@dataclass
class FieldCheck:
    id: int
    case_id: int
    equipment_id: str
    rule_id: str
    evidence_id: str
    question: str
    technician: str
    technician_name: Optional[str]
    status: str
    answer: Optional[str]
    message_id: Optional[str]
    chain: int
    created_at: str
    answered_at: Optional[str]
    error: Optional[str]

    @property
    def ref(self) -> str:
        return f"C{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "ref": self.ref}


class FieldCheckService:
    def __init__(self, database: Any, transport: Transport, roster: Optional[Dict[str, str]] = None,
                 ttl_hours: Optional[float] = None, max_chain: Optional[int] = None):
        self.database = database
        self.transport = transport
        self.roster = roster if roster is not None else load_roster()
        self.ttl = timedelta(hours=float(ttl_hours if ttl_hours is not None
                                         else os.getenv("ARVIS_FIELD_CHECK_TTL_H", "12")))
        self.max_chain = int(max_chain if max_chain is not None else os.getenv("ARVIS_FIELD_CHECK_MAX_CHAIN", "4"))
        self._lock = asyncio.Lock()
        self._ignored: set = set()
        self._follow_up: Optional[tuple] = None             # (case_id, chain) to ask after replying

    # ── storage ───────────────────────────────────────────────────────────
    async def _conn(self):
        conn = await self.database._get_async_connection()
        await conn.execute(_DDL)
        for stmt in _IDX:
            await conn.execute(stmt)
        return conn

    async def _rows(self, where: str = "", args: tuple = ()) -> List[FieldCheck]:
        conn = await self._conn()
        cols = ("id, case_id, equipment_id, rule_id, evidence_id, question, technician, technician_name, "
                "status, answer, message_id, chain, created_at, answered_at, error")
        async with conn.execute(f"SELECT {cols} FROM field_checks {where} ORDER BY id", args) as cur:
            return [FieldCheck(*r) for r in await cur.fetchall()]

    async def list_checks(self, status: Optional[str] = None) -> List[FieldCheck]:
        await self._expire()
        return await self._rows("WHERE status = ?", (status,)) if status else await self._rows()

    async def _update(self, check_id: int, **fields) -> None:
        conn = await self._conn()
        sets = ", ".join(f"{k} = ?" for k in fields)
        await conn.execute(f"UPDATE field_checks SET {sets} WHERE id = ?", (*fields.values(), check_id))
        await conn.commit()

    async def _expire(self) -> None:
        cutoff = (datetime.now() - self.ttl).isoformat(timespec="seconds")
        conn = await self._conn()
        await conn.execute("UPDATE field_checks SET status='expired' WHERE status='sent' AND created_at < ?",
                           (cutoff,))
        await conn.commit()

    # ── asking ────────────────────────────────────────────────────────────
    async def request(self, case_id: int, technician: str, *, chain: int = 1) -> FieldCheck:
        """Send the case's next question to a roster technician. Raises ValueError
        when there is nothing to ask (no such open case, no question left) or the
        technician is not on the roster."""
        number = normalize_number(technician)
        if number not in self.roster:
            raise ValueError(f"{technician} is not on the field technician roster (ARVIS_FIELD_TECHNICIANS)")
        from agent_commercial.fdd.diagnosis import list_cases
        case = next((c for c in await list_cases(self.database) if c.id == case_id), None)
        if case is None or case.status != "open":
            raise ValueError(f"case {case_id} is not an open diagnosis case")
        q = (case.diagnosis or {}).get("next_question")
        if not q or not q.get("question"):
            raise ValueError(f"case {case_id} has no open question — the diagnosis is as far as checks can take it")
        await self._expire()
        pending = [c for c in await self._rows("WHERE case_id = ? AND status = 'sent'", (case_id,))]
        if pending:
            return pending[0]                                   # one outstanding question per case

        conn = await self._conn()
        cur = await conn.execute(
            "INSERT INTO field_checks (case_id, equipment_id, rule_id, evidence_id, question, technician, "
            "technician_name, status, chain, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (case.id, case.equipment_id, case.rule_id, q["evidence_id"], q["question"], number,
             self.roster[number], "sent", chain, datetime.now().isoformat(timespec="seconds")))
        await conn.commit()
        check = (await self._rows("WHERE id = ?", (cur.lastrowid,)))[0]
        body = (f"ARVIS check — {case.equipment_id} (ref {check.ref})\n"
                f"{q['question']}\n"
                f"Reply YES, NO or NOT SURE.")
        try:
            msg_id = await self.transport.send_check(number, body, check.ref)
            await self._update(check.id, message_id=msg_id)
            check.message_id = msg_id
        except Exception as e:
            await self._update(check.id, status="failed", error=f"{type(e).__name__}: {e}")
            check.status = "failed"
            logger.warning(f"[FieldCheck] {check.ref} to {number} not delivered: {e}")
        return check

    # ── answers ───────────────────────────────────────────────────────────
    async def on_message(self, sender: str, text: str, reply_to: Optional[str] = None,
                         message_id: Optional[str] = None) -> Optional[str]:
        """Handle one inbound message. Returns the reply sent (None when the sender
        is not a roster technician, or the message was already handled)."""
        number = normalize_number(sender)
        if number not in self.roster:
            if number not in self._ignored:
                self._ignored.add(number)
                logger.info(f"[FieldCheck] ignoring message from {number}: not on the technician roster")
            return None
        async with self._lock:
            if message_id and not await self._first_time(message_id):
                return None                                 # a webhook retry of something already applied
            await self._expire()
            open_checks = await self._rows("WHERE technician = ? AND status = 'sent'", (number,))
            check = self._match(open_checks, text, reply_to)
            if check is None:
                if not open_checks:
                    reply = "No ARVIS check is waiting for you right now."
                else:
                    listed = ", ".join(f"{c.ref} {c.equipment_id}" for c in open_checks)
                    reply = f"You have {len(open_checks)} open checks ({listed}). Reply like \"C{open_checks[0].id} yes\"."
                await self._safe_send(number, reply)
                return reply

            answer = parse_answer(text)
            if answer is None:
                reply = f"{check.ref}: please reply YES, NO or NOT SURE.\n{check.question}"
                await self._safe_send(number, reply)
                return reply
            self._follow_up = None
            reply = await self._apply(check, number, answer)
            await self._safe_send(number, reply)
            if self._follow_up:                             # acknowledgement first, then the next question
                case_id, chain = self._follow_up
                await self.request(case_id, number, chain=chain)
            return reply

    async def _first_time(self, message_id: str) -> bool:
        conn = await self._conn()
        cur = await conn.execute("INSERT OR IGNORE INTO field_check_inbound (message_id, received_at) VALUES (?, ?)",
                                 (message_id, datetime.now().isoformat(timespec="seconds")))
        await conn.commit()
        return cur.rowcount == 1

    @staticmethod
    def _match(open_checks: List[FieldCheck], text: str, reply_to: Optional[str]) -> Optional[FieldCheck]:
        if reply_to:
            hit = next((c for c in open_checks if c.message_id == reply_to), None)
            if hit:
                return hit
        m = _REF.search(text or "")
        if m:
            return next((c for c in open_checks if c.id == int(m.group(1))), None)
        return open_checks[0] if len(open_checks) == 1 else None

    async def _apply(self, check: FieldCheck, number: str, answer: str) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        name = self.roster.get(number, number)
        if answer == "unsure":
            await self._update(check.id, status="unsure", answer="unsure", answered_at=now)
            return (f"Thanks {name} — noted as not sure. {check.equipment_id} is flagged for an "
                    "engineer to check in person.")

        from agent_commercial.fdd.diagnosis import answer_question
        case = await answer_question(self.database, check.case_id, check.evidence_id, answer,
                                     answered_by=f"whatsapp:{name}")
        await self._update(check.id, status="answered", answer=answer, answered_at=now)
        d = case.diagnosis or {}
        if d.get("kb_bust"):
            return (f"Thanks {name} — recorded. None of the known causes fit {check.equipment_id} any more; "
                    "an engineer will take it from here.")
        top = (d.get("posterior") or [{}])[0]
        msg = f"Thanks {name} — recorded. {check.equipment_id}: most likely {top.get('label')} ({top.get('p', 0):.0%})."

        nq = d.get("next_question")
        asked = {c.evidence_id for c in await self._rows("WHERE case_id = ?", (check.case_id,))}
        if nq and nq.get("evidence_id") not in asked and check.chain < self.max_chain:
            self._follow_up = (check.case_id, check.chain + 1)   # sent after this acknowledgement
            msg += " One more check follows."
        elif nq:
            msg += " That's enough from site for now — an engineer will review the rest."
        return msg

    async def on_delivery_failure(self, message_id: str, error: str) -> int:
        """The channel reported a check undelivered (e.g. outside WhatsApp's 24-hour
        window without a template). Mark it failed so nobody waits for an answer."""
        rows = await self._rows("WHERE message_id = ? AND status = 'sent'", (message_id,))
        for c in rows:
            await self._update(c.id, status="failed", error=error)
            logger.warning(f"[FieldCheck] {c.ref} to {c.technician} failed to deliver: {error}")
        return len(rows)

    async def _safe_send(self, to: str, body: str) -> None:
        try:
            await self.transport.send_text(to, body)
        except Exception as e:
            logger.warning(f"[FieldCheck] reply to {to} not delivered: {e}")


_service: Optional[FieldCheckService] = None


def get_field_check_service() -> Optional[FieldCheckService]:
    """The configured service, or None when no messaging channel is configured."""
    global _service
    if _service is None:
        from agent_commercial.messaging.evolution import EvolutionTransport
        transport = EvolutionTransport.from_env()
        if transport is None:
            return None
        from agent_commercial.database import get_database
        _service = FieldCheckService(get_database(), transport)
    return _service
