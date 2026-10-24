"""
ARVIS speaks up on its own — through the attention gate, plus a morning brief.

Every monitoring event goes to the attention gate (attention.py), which decides per
person: now, soon, the next brief, or not at all — with reasons on record.

Morning brief (ARVIS_OPS_BRIEF_HOUR, local): to each FM on workdays (on weekends and
holidays only if something is waiting for them), to owners weekly on
ARVIS_OPS_OWNER_BRIEF_DAY — and the morning after anything was held for them. It carries the building summary plus everything held for
that person since the last brief. If ARVIS was down at the brief hour, it goes out
at the next check before ARVIS_OPS_BRIEF_LATEST (11:00).

With an ops group (ARVIS_OPS_GROUP), the team also gets one morning summary there on
workdays — building status only; what was held for one person stays in their brief.

Anyone can ask for their brief at any time ("brief me" → brief_now): same content,
plus anything held for later today; it counts as today's brief.

Work orders that CAFM did not accept the first time are retried on the same clock,
and the person who raised one is told once it is in.

Reading rounds (manual_readings.py) go out on the same clock at their set times —
one message per round listing what to read, with the last value as a cross-check —
and readings that are overdue appear in the facilities manager's brief.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Optional

from agent_commercial.ops_engineer.ledger import utcnow

logger = logging.getLogger("arvis.ops.proactive")


class ProactiveEngineer:
    def __init__(self, *, people: Any, store: Any, gateway: Any, engineer: Any, gate: Any, calendar: Any,
                 roles: Any = None):
        self.people = people
        self.store = store
        self.gateway = gateway
        self.engineer = engineer
        self.gate = gate
        self.calendar = calendar
        self.roles = roles
        self.learning = None                     # Learning: learned normals are announced in the brief
        self.work_orders = None                  # WorkOrderLog: queued orders retried on this clock
        self.readings = None                     # ManualReadingStore: reading rounds + overdue readings
        self.clock = utcnow                      # aware UTC now (injectable, like the store's clock)
        self.brief_hour = int(os.getenv("ARVIS_OPS_BRIEF_HOUR", "7"))
        self.brief_latest = int(os.getenv("ARVIS_OPS_BRIEF_LATEST", "11"))
        self.owner_brief_day = os.getenv("ARVIS_OPS_OWNER_BRIEF_DAY", "Sunday")
        self._tasks: set = set()

    def attach(self, event_bus: Any) -> None:
        self.gate.attach(event_bus)

    async def _summary(self) -> str:
        if self.roles is None:
            return "Building status: unavailable"
        try:
            return (await self.roles.before_investigation("", {}, None))["prompt"]
        except Exception as e:
            logger.warning(f"[Ops] brief facts unavailable: {e}")
            return "Building status: unavailable"

    async def _normals(self) -> list:
        if self.learning is None:
            return []
        try:
            await self.learning.learn_normals()
            return await self.learning.unannounced_normals()
        except Exception as e:
            logger.warning(f"[Ops] learning normals failed: {e}")
            return []

    async def _send_brief(self, person: Any, now: datetime, summary: str, held: list, normals: list,
                          purpose: str) -> bool:
        """Compose and send one person's brief; only once it is delivered are the held
        items marked sent and the day's brief marked told."""
        facts = f"{self.calendar.describe(now)}\n{summary}"
        if self.readings is not None and person.role == "fm":
            try:
                overdue = await self.readings.overdue()
            except Exception as e:
                logger.warning(f"[Ops] overdue readings unavailable: {e}")
                overdue = []
            if overdue:
                facts += "\nHand-taken readings overdue: " + "; ".join(
                    f"{p.name} (last {last.observed_at[:16] if last else 'never'})" for p, last in overdue[:8])
        if held:
            facts += "\nHeld for this brief:\n" + "\n".join(f"- {i.title}: {i.facts}" for i in held)
        if normals:
            facts += ("\nLearned as normal for this building (dismissed repeatedly at these times) — I'll stop "
                      "flagging these; they can tell me to watch them again:\n" +
                      "\n".join(f"- {n['kind']} on {n['subject']}, {n['day_type']}s {n['hours']}" for n in normals))
        text = await self.engineer.compose(person, facts, purpose)
        if await self.gateway.send(person, text, kind="proactive") is None:
            return False                                     # retried at the next check
        day = self.calendar.local(now).strftime("%Y-%m-%d")
        await self.store.mark_told(person.number, f"brief:{day}", f"brief {day}")
        await self.gate.ledger.mark([i.id for i in held], "sent", now)
        for i in held:
            await self.store.mark_told(person.number, i.topic, i.title)
        return True

    async def morning_brief(self, now: Optional[datetime] = None) -> int:
        now = now or self.clock()
        local = self.calendar.local(now)
        day = local.strftime("%Y-%m-%d")
        summary = await self._summary()
        normals = await self._normals()
        weekly = local.strftime("%A") == self.owner_brief_day
        audience = list(self.people.by_role("fm")) + list(self.people.by_role("owner"))
        sent = 0
        announced = False
        for person in audience:
            if await self.store.told(person.number, f"brief:{day}"):
                continue
            held = [i for i in await self.gate.ledger.pending_for(person.number) if i.level == "DIGEST"]
            if person.role == "fm" and self.calendar.day_type(now) != "workday" and not held:
                continue                                     # quiet weekend: nothing to report, say nothing
            if person.role == "owner" and not (weekly or held):
                continue                                     # owners: weekly, or the morning after something big
            purpose = ("give their morning brief: what needs attention today first, what happened overnight, "
                       "what is waiting on technicians" if person.role == "fm" else
                       "give their weekly brief: building health, costs being addressed, what was fixed")
            mine = normals if person.role == "fm" else []
            if await self._send_brief(person, now, summary, held, mine, purpose):
                sent += 1
                announced = announced or bool(mine)
        if announced:                                        # every FM in this run heard them: once is enough
            await self.learning.mark_announced([n["id"] for n in normals])
        if self.calendar.day_type(now) == "workday" and await self._team_brief(now, day, summary):
            sent += 1
        return sent

    async def _team_brief(self, now: datetime, day: str, summary: str) -> bool:
        """The team's morning summary in the ops group — building status only; what was
        held for one person stays in their own brief."""
        group = getattr(self.gateway, "group", None)
        if not group or await self.store.told(group, f"brief:{day}"):
            return False
        from agent_commercial.ops_engineer.people import Person
        team = Person(name="the building team (ops group)", number=group, role="fm")
        text = await self.engineer.compose(team, f"{self.calendar.describe(now)}\n{summary}",
                                           "give the team's morning summary: what needs attention today and what "
                                           "is waiting on technicians — no personal items")
        if await self.gateway.send_group(text, kind="proactive") is None:
            return False                                     # retried at the next check
        await self.store.mark_told(group, f"brief:{day}", f"team brief {day}")
        return True

    async def brief_now(self, person: Any, now: Optional[datetime] = None) -> dict:
        """The brief, on request — everything held for them, at any level, goes with it."""
        now = now or self.clock()
        held = list(await self.gate.ledger.pending_for(person.number))
        normals = await self._normals() if person.role == "fm" else []
        purpose = ("give the brief they just asked for: what needs attention first, what you were holding for "
                   "them, what is waiting on technicians" if person.role != "owner" else
                   "give the brief they just asked for: building health, costs being addressed, what was fixed")
        sent = await self._send_brief(person, now, await self._summary(), held, normals, purpose)
        if sent and normals:
            await self.learning.mark_announced([n["id"] for n in normals])
        return {"sent": sent, "held_items_included": len(held) if sent else 0,
                **({} if sent else {"error": "the brief could not be delivered"})}

    async def send_rounds(self, now: Optional[datetime] = None) -> int:
        """Reading rounds whose time has come: one message each, to the person or the group."""
        if self.readings is None:
            return 0
        local = self.calendar.local(now or self.clock())
        sent = 0
        for r in await self.readings.rounds_due(local):
            pts = [p for p in [await self.readings.point(pid) for pid in r["point_ids"]] if p]
            if not pts:
                continue
            lines, lasts = [], []
            for i, p in enumerate(pts, 1):
                last = await self.readings.last(p.point_id)
                lasts.append(last)
                lines.append(f"{i}. {p.name}" + (f" ({p.unit})" if p.unit else "")
                             + (f" — last {last.value:g}" if last else ""))
            example = f"{pts[0].name.lower()} {lasts[0].value:g}" if lasts[0] else f"{pts[0].name.lower()} 42"
            text = (f"{r['name']} — time for these readings:\n" + "\n".join(lines)
                    + f"\nReply like “{example}”, one per line, or send a photo of each gauge.")
            if r["recipient"] == "group":
                msg = await self.gateway.send_group(text, kind="round")
            else:
                person = self.people.get(r["recipient"])
                if person is None:
                    logger.warning(f"[Ops] round {r['name']!r}: {r['recipient']} is not on the roster")
                    continue
                msg = await self.gateway.send(person, text, kind="round")
            if msg is not None:
                await self.readings.mark_round_sent(r["name"], r["slot"])
                sent += 1
        return sent

    async def retry_work_orders(self) -> int:
        if self.work_orders is None:
            return 0
        raised = await self.work_orders.retry_queued()
        for wo in raised:
            person = self.people.get(wo.get("raised_by_number") or "")
            if person is not None:
                await self.gateway.send(person, f"The work order for {wo['equipment_id']} is in the maintenance "
                                                f"system now: {wo['cafm_id']}.", kind="work_order")
        return len(raised)

    async def run(self, poll_seconds: int = 300) -> None:
        """The gate's worker and clock, and the brief at the brief hour (with catch-up)."""
        gate_task = asyncio.get_running_loop().create_task(self.gate.run())
        try:
            while True:
                try:
                    hour = self.calendar.local().hour
                    if self.brief_hour <= hour < self.brief_latest:
                        await self.morning_brief()
                    await self.retry_work_orders()
                    await self.send_rounds()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[Ops] brief scheduler error: {e}")
                await asyncio.sleep(poll_seconds)
        finally:
            gate_task.cancel()
