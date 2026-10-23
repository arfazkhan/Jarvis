"""
ARVIS speaks up on its own — when it matters, to whom it matters, once.

Events (published by the FDD sweep on the event bus):
  fdd_faults_confirmed   a fault newly confirmed by the rules → the facilities
                         manager; the owner too when the avoidable cost is large
  fdd_fix_verified       a recorded repair was re-checked → the facilities manager
                         (and the technician who reported it, if known); a verified fix
                         clears the "already told" mark so a recurrence is news again
Scheduled:
  morning brief          once a day at ARVIS_OPS_BRIEF_HOUR (local) to the
                         facilities manager(s), and to owners on ARVIS_OPS_OWNER_BRIEF_DAY

Judgement, not broadcast:
  * never the same topic twice to the same person (ops_notices)
  * quiet hours (ARVIS_OPS_QUIET_HOURS, default 22-6): confirmed faults wait for
    the morning brief — rule-FDD faults are confirmed over hours, not seconds
  * at most ARVIS_OPS_MAX_PER_HOUR unprompted messages per person (default 4);
    the rest is folded into the next brief
  * the wording is ARVIS's (engineer.compose), the facts are the engines'
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People, Person

logger = logging.getLogger("arvis.ops.proactive")


def _env_float(name: str, default: float) -> Optional[float]:
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class ProactiveEngineer:
    def __init__(self, *, people: People, store: ConversationStore, gateway: Any, engineer: Any,
                 roles: Any = None):
        self.people = people
        self.store = store
        self.gateway = gateway
        self.engineer = engineer
        self.roles = roles
        quiet = os.getenv("ARVIS_OPS_QUIET_HOURS", "22-6")
        try:
            a, b = (int(x) for x in quiet.split("-"))
            self.quiet = (a, b)
        except ValueError:
            self.quiet = (22, 6)
        self.max_per_hour = int(_env_float("ARVIS_OPS_MAX_PER_HOUR", 4))
        self.owner_cost = _env_float("ARVIS_OPS_OWNER_COST", 1000.0)
        self.brief_hour = int(_env_float("ARVIS_OPS_BRIEF_HOUR", 7))
        self.owner_brief_day = os.getenv("ARVIS_OPS_OWNER_BRIEF_DAY", "Sunday")
        self._tasks: Set[asyncio.Task] = set()

    # ── wiring ────────────────────────────────────────────────────────────
    def attach(self, event_bus: Any) -> None:
        event_bus.subscribe("fdd_faults_confirmed", lambda ev: self._spawn(self.on_faults(ev.get("payload") or {})))
        event_bus.subscribe("fdd_fix_verified", lambda ev: self._spawn(self.on_fixes(ev.get("payload") or {})))

    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            logger.error("[Ops] event received outside the event loop — dropped")
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _local_now(self) -> datetime:
        return self.engineer._local_now()

    def _quiet_now(self) -> bool:
        h, (a, b) = self._local_now().hour, self.quiet
        return (a <= h or h < b) if a > b else (a <= h < b)

    async def _say(self, person: Person, topic: str, facts: str, purpose: str, summary: str,
                   *, respect_quiet: bool = True) -> bool:
        if await self.store.told(person.number, topic):
            return False
        if respect_quiet and self._quiet_now():
            logger.info(f"[Ops] {topic} for {person.name} held for the morning brief (quiet hours)")
            return False
        if await self.store.proactive_count(person.number, 1.0) >= self.max_per_hour:
            logger.info(f"[Ops] {topic} for {person.name} folded into the next brief (hourly cap)")
            return False
        text = await self.engineer.compose(person, facts, purpose)
        if await self.gateway.send(person, text, kind="proactive") is None:
            return False
        await self.store.mark_told(person.number, topic, summary)
        return True

    # ── events ────────────────────────────────────────────────────────────
    async def on_faults(self, payload: Dict[str, Any]) -> int:
        sent = 0
        for f in payload.get("faults") or []:
            eq, rule = f.get("equipment_id"), f.get("rule_id")
            impact = f.get("impact") or {}
            cost = impact.get("cost")
            case = f.get("case") or {}
            causes = ((case.get("diagnosis") or {}).get("posterior") or [])[:2]
            question = ((case.get("diagnosis") or {}).get("next_question") or {}).get("question")
            facts = "\n".join(filter(None, [
                f"Newly confirmed fault: {f.get('headline') or (str(eq) + ' ' + str(f.get('title')))}",
                f"Avoidable cost: {cost} {impact.get('currency', '')} ({impact.get('basis', {}).get('energy', '')})"
                if cost is not None else "Cost impact: not quantified",
                ("Likely causes: " + "; ".join(f"{c['label']} (p={c['p']})" for c in causes)) if causes else None,
                f"Question that would settle it on site: {question}" if question else None,
                "Technicians on the roster: " + ", ".join(p.name for p in self.people.by_role("technician"))
                if question and self.people.by_role("technician") else None,
            ]))
            audience = list(self.people.by_role("fm"))
            if cost is not None and self.owner_cost is not None and float(cost) >= self.owner_cost:
                audience += self.people.by_role("owner")
            for person in audience:
                purpose = ("tell them about this newly confirmed fault: what it is, what it costs, the likely cause, "
                           "and offer to send the settling check to a technician" if person.role == "fm" else
                           "let them know about a costly problem the team is now handling, in business terms")
                if await self._say(person, f"fault:{eq}:{rule}", facts, purpose, f"{eq} {rule} fault"):
                    sent += 1
        return sent

    async def on_fixes(self, payload: Dict[str, Any]) -> int:
        sent = 0
        for v in payload.get("verifications") or []:
            eq, rule, status = v.get("equipment_id"), v.get("rule_id"), v.get("status")
            if status not in ("verified", "failed"):
                continue
            if status == "verified":
                await self.store.forget_topic(f"fault:{eq}:{rule}")       # a recurrence is news again
            facts = (f"Repair re-check on {eq} ({rule}): {'WORKED — fault no longer present' if status == 'verified' else 'did NOT fix it — fault still present'}.\n"
                     f"Detail: {v.get('reason', '')}\nRecorded: {v.get('note', '')}")
            audience = list(self.people.by_role("fm"))
            reporter = next((p for p in self.people.by_role("technician") if p.name in (v.get("note") or "")), None)
            if reporter:
                audience.append(reporter)
            for person in audience:
                purpose = ("tell them the outcome of the repair re-check" + ("" if status == "verified"
                           else ", and that the fault needs another look"))
                if await self._say(person, f"fix:{v.get('id')}", facts, purpose, f"{eq} repair {status}",
                                   respect_quiet=True):
                    sent += 1
        return sent

    # ── morning brief ─────────────────────────────────────────────────────
    async def morning_brief(self) -> int:
        now = self._local_now()
        day = now.strftime("%Y-%m-%d")
        facts = "Building status: unavailable"
        if self.roles is not None:
            try:
                facts = (await self.roles.before_investigation("", {}, None))["prompt"]
            except Exception as e:
                logger.warning(f"[Ops] brief facts unavailable: {e}")
        audience = list(self.people.by_role("fm"))
        if now.strftime("%A") == self.owner_brief_day:
            audience += self.people.by_role("owner")
        sent = 0
        for person in audience:
            purpose = ("give their morning brief: what needs attention today first, what's been verified, "
                       "anything waiting on technicians" if person.role == "fm" else
                       "give their weekly brief: building health, costs being addressed, what was fixed")
            if await self._say(person, f"brief:{day}", f"{now:%A %d %B}\n{facts}", purpose, f"brief {day}",
                               respect_quiet=False):
                sent += 1
        return sent

    async def run(self, poll_seconds: int = 300) -> None:
        """Background loop: sends the morning brief once, at the brief hour."""
        while True:
            try:
                if self._local_now().hour == self.brief_hour:
                    await self.morning_brief()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Ops] scheduler error: {e}")
            await asyncio.sleep(poll_seconds)
