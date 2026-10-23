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
        self.gate = None                       # AttentionGate, when proactive messaging is on
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ignored: set = set()
        self._tasks: set = set()

    def spawn_inbound(self, sender: str, text: str, message_id: Optional[str] = None,
                      reply_to: Optional[str] = None) -> asyncio.Task:
        """Handle a message in the background (the webhook must answer fast). Order per
        person is kept by the per-person lock inside on_inbound."""
        task = asyncio.get_running_loop().create_task(
            self._safe_inbound(sender, text, message_id=message_id, reply_to=reply_to))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _safe_inbound(self, sender: str, text: str, **kw) -> Optional[str]:
        try:
            return await self.on_inbound(sender, text, **kw)
        except Exception as e:
            # Never leave someone talking to silence: say so, and log it loudly.
            logger.error(f"[Ops] handling a message from {sender} failed: {type(e).__name__}: {e}", exc_info=True)
            person = self.people.get(sender)
            if person is not None:
                await self.send(person, "Something went wrong on my side handling that — it's logged. "
                                        "Could you send it again in a minute?")
            return None

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

    async def send_image(self, person: Person, png: bytes, caption: str, kind: str = "chart") -> Optional[str]:
        """A chart to one person. The thread keeps the caption, so ARVIS knows what it showed."""
        send_media = getattr(self.transport, "send_media", None)
        if send_media is None:
            logger.error("[Ops] this channel cannot send images")
            return None
        try:
            msg_id = await send_media(person.number, png, caption=caption, filename="arvis-trend.png",
                                      mimetype="image/png", delay_ms=typing_delay_ms(caption))
        except Exception as e:
            logger.error(f"[Ops] image to {person.name} not delivered: {type(e).__name__}: {e}")
            return None
        await self.store.append(person.number, "arvis", f"[chart] {caption}", kind=kind)
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

            reply = await self._acknowledgement(person, text, reply_to)
            if reply is not None:
                await self._observe(person, text, reply_to, ack=True)
                return reply

            reply = await self._fact_confirmation(person, text)
            if reply is not None:
                return reply

            if await self._is_check_answer(person, text, reply_to):
                await self.store.append(person.number, "person", text, kind="check")
                reply = await self.field_checks.on_message(person.number, text, reply_to=reply_to)
                if reply:
                    await self.store.append(person.number, "arvis", reply, kind="check")
                return reply

            await self.store.append(person.number, "person", text)
            reply = await self.engineer.respond(person, text)
            if await self.send(person, reply) is not None:
                await self.engineer.delivered(person, reply)
            await self._observe(person, text, reply_to, tools=getattr(self.engineer, "last_tools", {}).get(person.number))
            return reply

    async def _observe(self, person: Person, text: str, reply_to: Optional[str], tools=None, ack: bool = False):
        """Tell learning how the person reacted to what ARVIS sent them."""
        learning = getattr(self.engineer, "learning", None)
        if learning is None:
            return
        try:
            await learning.observe(person.number, text, reply_to=reply_to, tools=tools, ack=ack)
        except Exception as e:
            logger.warning(f"[Ops] engagement observe failed: {e}")

    async def _fact_confirmation(self, person: Person, text: str) -> Optional[str]:
        """A short yes/no right after ARVIS read a fact back: save it or drop it (no LLM)."""
        learning = getattr(self.engineer, "learning", None)
        if learning is None or len(text) > _CHECK_REPLY_MAX_CHARS:
            return None
        from agent_commercial.field_checks import parse_answer
        answer = parse_answer(text)
        if answer not in ("yes", "no"):
            return None
        fact = await learning.pending_fact(person.number, within_hours=1.0)
        if fact is None:
            return None
        await self.store.append(person.number, "person", text, kind="fact")
        settled = await learning.settle_fact(fact.id, answer == "yes")
        if answer == "yes":
            await self.engineer.remember_confirmed_fact(settled)
            reply = f"Saved — I'll remember that: {settled.statement}"
        else:
            reply = "OK, I won't save that."
        await self.send(person, reply, kind="fact")
        return reply

    async def _acknowledgement(self, person: Person, text: str, reply_to: Optional[str]) -> Optional[str]:
        """'on it' / 'seen' / 'تمام' to an alert awaiting acknowledgement: deterministic,
        so it works with the language model down. Stops the escalation ladder and
        acknowledges the underlying BMS alarm or advisory too."""
        if self.gate is None:
            return None
        from agent_commercial.ops_engineer.attention import parse_ack
        if not parse_ack(text):
            return None
        alerts = await self.gate.ledger.open_alerts(person.number)
        if not alerts:
            return None
        target = next((a for a in alerts if reply_to and a["message_id"] == reply_to), alerts[0])
        await self.store.append(person.number, "person", text, kind="ack")
        await self.gate.acknowledge(target["topic"], person, note=text)
        reply = f"Thanks {person.first_name} — noted, I'll stop chasing: {target['title']}."
        await self.send(person, reply, kind="ack")
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
