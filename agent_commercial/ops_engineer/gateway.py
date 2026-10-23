"""
Inbound WhatsApp → the right handler; outbound → paced like a person.

  * The number is the identity: people not on the roster are ignored.
  * Each inbound message is handled once (the channel retries webhooks) and each
    person's messages are handled in order, one at a time.
  * A short YES / NO / NOT SURE from someone who owes ARVIS a field check is that
    check's answer (deterministic path). Everything else goes to the engineer.
  * Replies are sent with a typing pause proportional to their length, and every
    message — theirs and ARVIS's — is kept in the thread memory.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from agent_commercial.ops_engineer.engineer import OpsEngineer
from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People, Person

logger = logging.getLogger("arvis.ops.gateway")

_CHECK_REPLY_MAX_CHARS = 60      # longer messages are conversation, even if they start with "yes"


def typing_delay_ms(text: str) -> int:
    return int(min(4000, 600 + 25 * len(text or "")))


class OpsGateway:
    def __init__(self, *, transport: Any, people: People, store: ConversationStore, engineer: OpsEngineer,
                 field_checks: Any = None):
        self.transport = transport
        self.people = people
        self.store = store
        self.engineer = engineer
        self.field_checks = field_checks
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ignored: set = set()

    async def send(self, person: Person, text: str, kind: str = "chat") -> Optional[str]:
        """Send to one person, paced, and remember it. Returns the message id (None if it failed)."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            msg_id = await self.transport.send_text(person.number, text, delay_ms=typing_delay_ms(text))
        except Exception as e:
            logger.error(f"[Ops] message to {person.name} not delivered: {type(e).__name__}: {e}")
            return None
        await self.store.append(person.number, "arvis", text, kind=kind)
        return msg_id

    async def on_inbound(self, sender: str, text: str, message_id: Optional[str] = None,
                         reply_to: Optional[str] = None) -> Optional[str]:
        person = self.people.get(sender)
        if person is None:
            if sender not in self._ignored:
                self._ignored.add(sender)
                logger.info(f"[Ops] ignoring {sender}: not on the site roster (ARVIS_PEOPLE)")
            return None
        if message_id and not await self.store.first_time(message_id):
            return None
        lock = self._locks.setdefault(person.number, asyncio.Lock())
        async with lock:
            text = (text or "").strip()
            if not text:
                reply = "I can read text and transcribed voice notes — photos and files I can't use yet. Could you type it?"
                await self.store.append(person.number, "person", "[non-text message]")
                await self.send(person, reply)
                return reply

            if await self._is_check_answer(person, text, reply_to):
                await self.store.append(person.number, "person", text, kind="check")
                reply = await self.field_checks.on_message(person.number, text, reply_to=reply_to)
                if reply:
                    await self.store.append(person.number, "arvis", reply, kind="check")
                return reply

            await self.store.append(person.number, "person", text)
            reply = await self.engineer.respond(person, text)
            await self.send(person, reply)
            return reply

    async def _is_check_answer(self, person: Person, text: str, reply_to: Optional[str]) -> bool:
        if self.field_checks is None or person.role != "technician":
            return False
        from agent_commercial.field_checks import parse_answer
        if parse_answer(text) is None:
            return False
        pending = [c for c in await self.field_checks.list_checks("sent") if c.technician == person.number]
        if not pending:
            return False
        return bool(reply_to and any(c.message_id == reply_to for c in pending)) or len(text) <= _CHECK_REPLY_MAX_CHARS
