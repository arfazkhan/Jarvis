"""
ARVIS speaks up on its own — through the attention gate, plus a morning brief.

Every monitoring event goes to the attention gate (attention.py), which decides per
person: now, soon, the next brief, or not at all — with reasons on record.

Morning brief (ARVIS_OPS_BRIEF_HOUR, local): to each FM on workdays (on weekends and
holidays only if something is waiting for them), to owners weekly on
ARVIS_OPS_OWNER_BRIEF_DAY — and the morning after anything was held for them. It carries the building summary plus everything held for
that person since the last brief. If ARVIS was down at the brief hour, it goes out
at the next check before ARVIS_OPS_BRIEF_LATEST (11:00).
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
        self.brief_hour = int(os.getenv("ARVIS_OPS_BRIEF_HOUR", "7"))
        self.brief_latest = int(os.getenv("ARVIS_OPS_BRIEF_LATEST", "11"))
        self.owner_brief_day = os.getenv("ARVIS_OPS_OWNER_BRIEF_DAY", "Sunday")
        self._tasks: set = set()

    def attach(self, event_bus: Any) -> None:
        self.gate.attach(event_bus)

    async def morning_brief(self, now: Optional[datetime] = None) -> int:
        now = now or utcnow()
        local = self.calendar.local(now)
        day = local.strftime("%Y-%m-%d")
        summary = "Building status: unavailable"
        if self.roles is not None:
            try:
                summary = (await self.roles.before_investigation("", {}, None))["prompt"]
            except Exception as e:
                logger.warning(f"[Ops] brief facts unavailable: {e}")
        weekly = local.strftime("%A") == self.owner_brief_day
        audience = list(self.people.by_role("fm")) + list(self.people.by_role("owner"))
        sent = 0
        for person in audience:
            topic = f"brief:{day}"
            if await self.store.told(person.number, topic):
                continue
            held = [i for i in await self.gate.ledger.pending_for(person.number) if i.level == "DIGEST"]
            if person.role == "fm" and self.calendar.day_type(now) != "workday" and not held:
                continue                                     # quiet weekend: nothing to report, say nothing
            if person.role == "owner" and not (weekly or held):
                continue                                     # owners: weekly, or the morning after something big
            facts = f"{self.calendar.describe(now)}\n{summary}"
            if held:
                facts += "\nHeld for this brief:\n" + "\n".join(f"- {i.title}: {i.facts}" for i in held)
            purpose = ("give their morning brief: what needs attention today first, what happened overnight, "
                       "what is waiting on technicians" if person.role == "fm" else
                       "give their weekly brief: building health, costs being addressed, what was fixed")
            text = await self.engineer.compose(person, facts, purpose)
            if await self.gateway.send(person, text, kind="proactive") is None:
                continue                                     # retried at the next check
            await self.store.mark_told(person.number, topic, f"brief {day}")
            await self.gate.ledger.mark([i.id for i in held], "sent", now)
            for i in held:
                await self.store.mark_told(person.number, i.topic, i.title)
            sent += 1
        return sent

    async def run(self, poll_seconds: int = 300) -> None:
        """The gate's worker and clock, and the brief at the brief hour (with catch-up)."""
        gate_task = asyncio.get_running_loop().create_task(self.gate.run())
        try:
            while True:
                try:
                    hour = self.calendar.local().hour
                    if self.brief_hour <= hour < self.brief_latest:
                        await self.morning_brief()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[Ops] brief scheduler error: {e}")
                await asyncio.sleep(poll_seconds)
        finally:
            gate_task.cancel()
