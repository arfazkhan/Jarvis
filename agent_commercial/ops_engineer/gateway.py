"""
Inbound WhatsApp → the right handler; outbound → paced like a person.

  * The number is the identity: people not on the roster are ignored.
  * Each inbound message is handled once (the channel retries webhooks) and each
    person's messages are handled in order, one at a time.
  * Voice notes are transcribed on the site box and then handled exactly like typed
    text (so a spoken "yes" answers a check). Photos are kept as evidence, read by
    the vision model, and go to the engineer with what they show. Videos and files:
    ARVIS says it can't use them yet.
  * Readings taken by people (manual_readings.py): a reply to a reading round fills
    in the readings it names; a gauge photo of a tracked point becomes a proposed
    reading that the person confirms; a doubtful reading waits for "yes", "no" or
    the right number. All deterministic — no language model in the loop.
  * A short YES / NO / NOT SURE from someone who owes ARVIS a field check is that
    check's answer (deterministic path). Everything else goes to the engineer.
  * The ops group (ARVIS_OPS_GROUP): ARVIS reads along quietly (that is context) and
    speaks only when addressed — @mentioned, named, or replied to. Its answer goes to
    the group; personal things stay in 1:1 chats. "On it" as a reply to an alert it
    posted there acknowledges that alert.
  * Replies are sent with a typing pause proportional to their length, and every
    message — theirs and ARVIS's — is kept in the thread memory, with ARVIS's
    WhatsApp message id.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import replace
from typing import Any, Dict, Optional, Tuple

from agent_commercial.messaging.evolution import InboundMessage
from agent_commercial.ops_engineer.engineer import OpsEngineer
from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People, Person

logger = logging.getLogger("arvis.ops.gateway")

_CHECK_REPLY_MAX_CHARS = 60      # longer messages are conversation, even if they start with "yes"
_EQUIPMENT = re.compile(r"\b([A-Za-z]{2,6})[-_ ]?(\d{1,4})\b")
_NAMED = re.compile(r"\barvis\b", re.IGNORECASE)
_MENTION_TOKEN = re.compile(r"@\d{6,}\s*")
_CANT_USE = {"video": "videos", "document": "files", "other": "stickers"}


def typing_delay_ms(text: str) -> int:
    return int(min(4000, 600 + 25 * len(text or "")))


def _equipment_ids(text: str) -> list:
    return [f"{a.upper()}-{b}" for a, b in _EQUIPMENT.findall(text or "")]


class OpsGateway:
    def __init__(self, *, transport: Any, people: People, store: ConversationStore, engineer: OpsEngineer,
                 field_checks: Any = None, group: Optional[str] = None):
        self.transport = transport
        self.people = people
        self.store = store
        self.engineer = engineer
        self.field_checks = field_checks
        self.gate = None                       # AttentionGate, when proactive messaging is on
        self.group = group                     # the ops group jid (ARVIS_OPS_GROUP), when group mode is on
        self.media_store = None                # MediaStore: photos / voice notes kept as evidence
        self.transcriber = None                # LocalTranscriber (voice notes, on the site box)
        self.photos = None                     # PhotoReader (vision model)
        self.readings = None                   # ManualReadingStore (readings taken by people)
        self._group_turn: Dict[str, str] = {}  # person → group, while answering them in the group
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ignored: set = set()
        self._tasks: set = set()

    def spawn_inbound(self, sender: str, text: str, message_id: Optional[str] = None,
                      reply_to: Optional[str] = None) -> asyncio.Task:
        return self.spawn_message(InboundMessage(sender=sender, text=text, message_id=message_id or "",
                                                 reply_to=reply_to))

    def spawn_message(self, m: InboundMessage) -> asyncio.Task:
        """Handle a message in the background (the webhook must answer fast). Order per
        person (and in the group) is kept by the locks inside on_message."""
        task = asyncio.get_running_loop().create_task(self._safe_message(m))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _safe_message(self, m: InboundMessage) -> Optional[str]:
        try:
            return await self.on_message(m)
        except Exception as e:
            # Never leave someone talking to silence: say so, and log it loudly.
            logger.error(f"[Ops] handling a message from {m.sender} failed: {type(e).__name__}: {e}", exc_info=True)
            person = self.people.get(m.sender)
            if person is not None:
                await self._deliver(m.group or person.number, "Something went wrong on my side handling that — "
                                                              "it's logged. Could you send it again in a minute?")
            return None

    # ── sending ───────────────────────────────────────────────────────────
    async def _deliver(self, to: str, text: str, kind: str = "chat",
                       meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        text = (text or "").strip()
        if not text:
            return None
        try:
            msg_id = await self.transport.send_text(to, text, delay_ms=typing_delay_ms(text))
        except Exception as e:
            logger.error(f"[Ops] message to {to} not delivered: {type(e).__name__}: {e}")
            return None
        await self.store.append(to, "arvis", text, kind=kind, meta={**(meta or {}), "message_id": msg_id})
        return msg_id

    async def send(self, person: Person, text: str, kind: str = "chat") -> Optional[str]:
        """Send to one person, paced, and remember it. Returns the message id (None if it failed)."""
        return await self._deliver(person.number, text, kind=kind)

    async def send_group(self, text: str, kind: str = "proactive",
                         meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Post in the ops group (None when there is no group, or it failed)."""
        if not self.group:
            return None
        return await self._deliver(self.group, text, kind=kind, meta=meta)

    async def send_image(self, person: Person, png: bytes, caption: str, kind: str = "chart") -> Optional[str]:
        """A chart — to the person, or to the group when they asked for it there. The thread
        keeps the caption, so ARVIS knows what it showed."""
        to = self._group_turn.get(person.number, person.number)
        send_media = getattr(self.transport, "send_media", None)
        if send_media is None:
            logger.error("[Ops] this channel cannot send images")
            return None
        try:
            msg_id = await send_media(to, png, caption=caption, filename="arvis-trend.png",
                                      mimetype="image/png", delay_ms=typing_delay_ms(caption))
        except Exception as e:
            logger.error(f"[Ops] image to {to} not delivered: {type(e).__name__}: {e}")
            return None
        await self.store.append(to, "arvis", f"[chart] {caption}", kind=kind, meta={"message_id": msg_id})
        return msg_id

    # ── receiving ─────────────────────────────────────────────────────────
    async def on_inbound(self, sender: str, text: str, message_id: Optional[str] = None,
                         reply_to: Optional[str] = None) -> Optional[str]:
        return await self.on_message(InboundMessage(sender=sender, text=text, message_id=message_id or "",
                                                    reply_to=reply_to))

    async def on_message(self, m: InboundMessage) -> Optional[str]:
        person = self.people.get(m.sender)
        if person is None:
            if m.sender not in self._ignored:
                self._ignored.add(m.sender)
                logger.info(f"[Ops] ignoring {m.sender}: not on the site roster (ARVIS_PEOPLE)")
            return None
        if m.message_id and not await self.store.first_time(m.message_id):
            return None
        if m.group:
            if m.group != self.group:
                return None
            async with self._locks.setdefault(m.group, asyncio.Lock()):
                return await self._group_message(person, m)
        async with self._locks.setdefault(person.number, asyncio.Lock()):
            text, stored, reply = await self._as_text(person, m, to=person.number)
            if text is None:
                return reply
            return await self._handle(person, text, stored, m.reply_to, photo=m.kind == "image")

    async def _handle(self, person: Person, text: str, stored: str, reply_to: Optional[str],
                      photo: bool = False) -> Optional[str]:
        if not photo:
            reply = await self._acknowledgement(person, text, reply_to)
            if reply is not None:
                await self._observe(person, text, reply_to, ack=True)
                return reply

            reply = await self._reading_reply(person, text)
            if reply is not None:
                return reply

            reply = await self._fact_confirmation(person, text)
            if reply is not None:
                return reply

            if await self._is_check_answer(person, text, reply_to):
                await self.store.append(person.number, "person", stored, kind="check")
                reply = await self.field_checks.on_message(person.number, text, reply_to=reply_to)
                if reply:
                    await self.store.append(person.number, "arvis", reply, kind="check")
                return reply

        await self.store.append(person.number, "person", stored)
        reply = await self.engineer.respond(person, stored)
        if await self.send(person, reply) is not None:
            await self.engineer.delivered(person, reply)
        await self._observe(person, text, reply_to, tools=getattr(self.engineer, "last_tools", {}).get(person.number))
        return reply

    async def _as_text(self, person: Person, m: InboundMessage, to: str) -> Tuple[Optional[str], str, Optional[str]]:
        """(text to act on, text to keep in the thread, reply already sent when there is no text)."""
        if m.kind == "text":
            text = (m.text or "").strip()
            if text:
                return text, text, None
            return None, "", await self._cannot(person, to, "[non-text message]",
                                                "I can read text, voice notes and photos — could you type it?")
        if m.kind == "voice":
            text = (m.text or "").strip()                    # Evolution's own transcript, when it made one
            if not text:
                text = await self._transcribe(person, m, to)
            if not text:
                why = getattr(self.transcriber, "error", None) if self.transcriber is not None \
                    else "voice transcription isn't set up on this site"
                return None, "", await self._cannot(
                    person, to, "[voice note — not transcribed]",
                    "I couldn't make out that voice note" + (f" ({why})" if why else "")
                    + ". Could you type it, or send it again?")
            return text, f"[voice note] {text}", None
        if m.kind == "image":
            return await self._photo(person, m, to)
        what = _CANT_USE.get(m.kind, "that kind of message")
        return None, "", await self._cannot(person, to, f"[{m.kind}] {m.caption}".strip(),
                                            f"I can't use {what} yet — text, voice notes and photos I can. "
                                            "Could you tell me what it shows?")

    async def _cannot(self, person: Person, to: str, stored: str, reply: str) -> str:
        await self.store.append(to, "person", stored if to == person.number else f"{person.first_name}: {stored}")
        await self._deliver(to, reply)
        return reply

    async def _fetch(self, m: InboundMessage) -> Optional[Tuple[bytes, str]]:
        fetch = getattr(self.transport, "fetch_media", None)
        if fetch is None or not m.media:
            return None
        try:
            return await fetch(m.media)
        except Exception as e:
            logger.error(f"[Ops] could not download {m.kind} {m.message_id}: {type(e).__name__}: {e}")
            return None

    async def _transcribe(self, person: Person, m: InboundMessage, to: str) -> Optional[str]:
        if self.transcriber is None:
            return None
        got = await self._fetch(m)
        if got is None:
            self.transcriber.error = "it didn't come through to me"
            return None
        audio, mimetype = got
        result = await self.transcriber.transcribe(audio)
        text = (result or ("", ""))[0].strip()
        if self.media_store is not None:
            try:
                mid = await self.media_store.save(number=person.number, thread=to, kind="voice", data=audio,
                                                  mimetype=mimetype, message_id=m.message_id)
                if text:
                    await self.media_store.annotate(mid, transcript=text)
            except Exception as e:
                logger.warning(f"[Ops] voice note not kept: {e}")
        return text or None

    async def _equipment_for(self, person: Person, caption: str) -> Optional[str]:
        """What a photo is about: named in its caption, else the check this technician owes,
        else what they were just talking about."""
        named = _equipment_ids(caption)
        if named:
            return named[0]
        if self.field_checks is not None and person.role == "technician":
            try:
                mine = [c for c in await self.field_checks.list_checks("sent") if c.technician == person.number]
                if mine:
                    return mine[0].equipment_id
            except Exception as e:
                logger.warning(f"[Ops] field checks unavailable: {e}")
        for t in reversed(await self.store.recent(person.number, limit=4)):
            named = _equipment_ids(t.text)
            if named:
                return named[0]
        return None

    async def _photo(self, person: Person, m: InboundMessage, to: str) -> Tuple[Optional[str], str, Optional[str]]:
        caption = (m.caption or "").strip()
        got = await self._fetch(m)
        if got is None:
            return None, "", await self._cannot(person, to, f"[photo — not received] {caption}".strip(),
                                                "That photo didn't come through to me — could you send it again?")
        image, mimetype = got
        equipment = await self._equipment_for(person, caption)
        media_id = None
        if self.media_store is not None:
            try:
                media_id = await self.media_store.save(number=person.number, thread=to, kind="image", data=image,
                                                       mimetype=mimetype, caption=caption, equipment_id=equipment,
                                                       message_id=m.message_id)
            except Exception as e:
                logger.error(f"[Ops] photo not kept: {e}")
        question = await self._photo_reading(person, image, caption, equipment, media_id, to)
        if question is not None:
            return None, "", question
        seen = await self.photos.read(image, caption) if self.photos is not None else None
        if seen and media_id is not None:
            await self.media_store.annotate(media_id, description=seen)
        label = ("[photo" + (f" #{media_id}" if media_id is not None else "")
                 + (f" of {equipment}" if equipment else "") + "]")
        text = f"{label} {caption}".strip()
        if seen:
            text += ("\nWhat it shows (read by a vision model — it may be wrong; confirm before relying on it):\n"
                     + seen)
        else:
            why = getattr(self.photos, "error", None) or "no vision model on this site"
            text += f"\n(I could not look at the photo itself: {why}." + (" It is kept as evidence.)" if media_id
                                                                          else ")")
        return text, text, None

    # ── readings taken by people ─────────────────────────────────────────
    async def _reading_reply(self, person: Person, text: str) -> Optional[str]:
        """A yes / no / number for a reading that was waiting, or a reply to a reading round."""
        if self.readings is None:
            return None
        from agent_commercial.field_checks import parse_answer
        from agent_commercial.manual_readings import Parsed, convert, parse_numbers, parse_numeric
        pend = await self.readings.pending_for(person.number)
        if pend is not None and len(text) <= _CHECK_REPLY_MAX_CHARS:
            num = parse_numeric(text)
            answer = None if isinstance(num, Parsed) else parse_answer(text)
            mp = await self.readings.point(pend.point_id)
            name = mp.name if mp else pend.point_id
            reply = None
            if isinstance(num, Parsed):
                v = convert(num.value, num.unit, pend.unit)
                if v is None:
                    reply = f"{name} is tracked in {pend.unit} — could you send it in {pend.unit}?"
                else:
                    await self.readings.confirm(pend.id, value=v, by=person.name)
                    reply = f"Saved: {name} {v:g} {pend.unit}.".replace("  ", " ")
            elif answer == "yes":
                await self.readings.confirm(pend.id, by=person.name)
                reply = f"Saved: {name} {pend.value:g} {pend.unit}.".replace("  ", " ")
            elif answer in ("no", "unsure"):
                await self.readings.reject(pend.id)
                reply = f"OK, I won't use that reading of {name}. Send the right number when you have it."
            if reply is not None:
                await self.store.append(person.number, "person", text, kind="reading")
                await self.send(person, reply, kind="reading")
                return reply
        due = await self.readings.open_round_points(person.number)
        if not due:
            return None
        found = parse_numbers(text)
        if not found:
            return None
        got, doubtful = [], []
        for item in found:
            mp = due[0] if len(found) == 1 and len(due) == 1 and not item.label \
                else await self.readings.find_point(item.label, candidates=due)
            if mp is None:
                continue
            try:
                r = await self.readings.record(mp.point_id, item.value, unit=item.unit, method="round",
                                               technician=person.number, raw_text=text)
            except ValueError as e:
                doubtful.append(str(e))
                continue
            (got if r.status in ("confirmed", "verification") else doubtful).append(
                f"{mp.name} {r.value:g} {r.unit}".strip() if r.status != "pending_confirm"
                else f"{mp.name} {r.value:g} {r.unit} — {r.note}; is that right?")
            due = [d for d in due if d.point_id != mp.point_id]
        if not got and not doubtful:
            return None
        lines = []
        if got:
            lines.append("Got it: " + "; ".join(got) + ".")
        lines += doubtful
        lines.append(("Still need: " + ", ".join(d.name for d in due) + ".") if due else "That's the round done — thanks.")
        reply = "\n".join(lines)
        await self.store.append(person.number, "person", text, kind="reading")
        await self.send(person, reply, kind="reading")
        return reply

    async def _photo_reading(self, person: Person, image: bytes, caption: str, equipment: Optional[str],
                             media_id: Optional[int], to: str) -> Optional[str]:
        """A gauge photo of a tracked point: read its value, and ask the person to confirm it."""
        if self.readings is None or self.photos is None or not hasattr(self.photos, "read_value"):
            return None
        cands = await self.readings.open_round_points(person.number)
        if not cands and equipment:
            cands = await self.readings.points(equipment)
        cands = [p for p in cands if p.capture in ("photo", "either")]
        if not cands:
            return None
        got = await self.photos.read_value(image, [{"point_id": p.point_id, "name": p.name, "unit": p.unit}
                                                   for p in cands], caption)
        if got is None:
            return None
        try:
            r = await self.readings.record(got["point_id"], got["value"], unit=got["unit"], method="photo_ocr",
                                           technician=person.number, raw_text=caption or None,
                                           media_ref=f"ops_media:{media_id}" if media_id is not None else None)
        except ValueError as e:
            logger.info(f"[Ops] photo reading not used: {e}")
            return None
        name = next(p.name for p in cands if p.point_id == r.point_id)
        if r.status == "verification":
            question = (f"The photo reads {r.value:g} {r.unit} for {name}; {r.note}. "
                        "Noted as a check on that sensor.").replace("  ", " ")
        else:
            question = (f"From the photo I read {r.value:g} {r.unit} for {name} — is that right? "
                        "Reply yes, no, or the correct number.").replace("  ", " ")
        label = f"[photo #{media_id} of {equipment or r.point_id}] {caption}".strip()
        await self.store.append(to, "person", label if to == person.number else f"{person.first_name}: {label}",
                                kind="reading")
        await self._deliver(to, question, kind="reading")
        return question

    # ── the ops group ─────────────────────────────────────────────────────
    async def _addressed(self, m: InboundMessage) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Is ARVIS being spoken to? Returns (addressed, the ARVIS message replied to)."""
        own = await self.store.own_ids()
        if m.own_jid and m.own_jid not in own:
            await self.store.add_own_id(m.own_jid)
            own.add(m.own_jid)
        ours = await self.store.arvis_message(m.group, m.reply_to) if m.reply_to else None
        if ours is not None and m.quoted_author and m.quoted_author not in own:
            # A reply to ARVIS carries ARVIS's own group identity (its @lid): learn it,
            # so @mentions by that id are recognised from now on.
            await self.store.add_own_id(m.quoted_author)
            own.add(m.quoted_author)
        named = bool(_NAMED.search(m.text or "") or _NAMED.search(m.caption or ""))
        return bool(ours is not None or named or any(j in own for j in m.mentions)), ours

    async def _group_message(self, person: Person, m: InboundMessage) -> Optional[str]:
        addressed, ours = await self._addressed(m)
        said = _MENTION_TOKEN.sub("", m.text or "").strip()
        if not addressed:
            # Read along: what the team says is context for when ARVIS is asked.
            heard = said or f"[{m.kind}] {m.caption}".strip()
            await self.store.append(m.group, "person", f"{person.first_name}: {heard}", kind="group")
            return None
        if ours and ours.get("topic") and self.gate is not None:
            from agent_commercial.ops_engineer.attention import parse_ack
            if parse_ack(said):
                await self.store.append(m.group, "person", f"{person.first_name}: {said}", kind="ack")
                await self.gate.acknowledge(ours["topic"], person, note=said)
                reply = f"Thanks {person.first_name} — it's yours, I'll stop chasing."
                await self._deliver(m.group, reply, kind="ack")
                return reply
        if m.kind == "text":
            m = replace(m, text=said)
        text, stored, reply = await self._as_text(person, m, to=m.group)
        if text is None:
            return reply
        line = f"{person.first_name}: {stored}"
        await self.store.append(m.group, "person", line)
        self._group_turn[person.number] = m.group
        try:
            reply = await self.engineer.respond(person, line, thread=m.group)
        finally:
            self._group_turn.pop(person.number, None)
        if await self._deliver(m.group, reply) is not None:
            await self.engineer.delivered(person, reply)
        return reply

    # ── deterministic paths ───────────────────────────────────────────────
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
