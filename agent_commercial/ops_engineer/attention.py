"""
The attention gate — ARVIS speaks only when it is worth someone's attention.

Every Signal (signals.py), for every person it could concern, gets one deterministic
decision, logged with its reasons (ops_decisions):

  NOW     interrupt now. Breaks quiet hours only for critical / life-safety /
          monitoring loss. Safety messages use a fixed template (no LLM — they must
          go out even when the model is down). Safety, critical, high alarms and
          monitoring loss wait for an acknowledgement and escalate if nobody gives one.
  SOON    tell them during working time, batched into one message, not while they
          are mid-conversation with ARVIS; non-critical alarms first wait to see
          whether they clear by themselves.
  DIGEST  fold into the next brief (held = queued, never dropped).
  DROP    not worth a message: already told, cleared, or not theirs.

Rules, in order (each appends a reason):
  clear       a signal that ends another resolves it, cancels what was queued about
              it, stops its ladder, and tells only the people who were told about it
  audience    fm: everything · owner: safety, critical, cost ≥ ARVIS_OPS_OWNER_COST,
              monitoring · technician: what concerns them (their check, their repair)
  novelty     already told and nothing material changed → DROP
  base        critical/safety/high → NOW · medium → SOON · low/info → DIGEST
  llm cap     a language-model conclusion never interrupts unless an open alarm or
              confirmed fault on the same equipment backs it → at most SOON
  calendar    quiet hours: anything not critical/safety → DIGEST; unoccupied
              (night/weekend/holiday): NOW→SOON, medium SOON→DIGEST
  handling    someone is already on it → one level down (never for safety)
  preference  what the person asked for: mute → DROP, digest-only → at most DIGEST
  normal      matches a learned "normal for this building" pattern → DROP
  engagement  they consistently ignore/dismiss this kind → one level quieter for them
              (the three above never apply to safety)
  rate        over ARVIS_OPS_MAX_PER_HOUR unprompted messages → DIGEST (not safety)

No language-model calls in the decision itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agent_commercial.ops_engineer.ledger import SignalLedger, utcnow
from agent_commercial.ops_engineer.people import People, Person
from agent_commercial.ops_engineer.signals import NORMALISERS, SEVERITIES, Signal, to_signals

logger = logging.getLogger("arvis.ops.attention")

LEVELS = ("DROP", "DIGEST", "SOON", "NOW")

_ACK = re.compile(r"^\s*(on\s*it|seen|got\s*it|ok(ay)?|noted|checking|on\s*my\s*way|will\s*check|ack(nowledged)?|"
                  r"copy|roger|sure|👍|✅|تمام|حاضر|شفت|ماشي|طيب|ابشر|أبشر)\b[\s.!👍]*$", re.IGNORECASE)


def parse_ack(text: str) -> bool:
    t = (text or "").strip()
    return 0 < len(t) <= 40 and bool(_ACK.match(t))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Decision:
    level: str
    reasons: List[Dict[str, str]] = field(default_factory=list)

    def because(self, code: str, detail: str = "") -> "Decision":
        self.reasons.append({"code": code, "detail": detail})
        return self


def _down(level: str) -> str:
    return {"NOW": "SOON", "SOON": "DIGEST"}.get(level, level)


_PURPOSE = {
    "fdd_fault": ("tell them about this newly confirmed fault: what it is, what it costs, the likely cause, "
                  "and offer to send the settling check to a technician"),
    "fdd_fix": "tell them the outcome of the repair re-check",
    "alarm": "tell them about this BMS alarm and what you would check first",
    "monitoring": "tell them you have lost sight of (part of) the building and what is affected",
    "investigation": ("share what your investigation concluded and what you would do next — make clear it is "
                      "your analysis"),
    "advisory": "share this advisory and what you would do next — make clear it is your analysis",
    "drift": "mention the sustained deviation you are watching and that an investigation is running",
    "field_check": "tell them the check they asked for did not get through, and offer to resend or ask someone else",
}


class AttentionGate:
    def __init__(self, *, people: People, store: Any, ledger: SignalLedger, calendar: Any, situation: Any,
                 engineer: Any, gateway: Any, state_engine: Any = None, advisories: Any = None):
        self.people = people
        self.store = store
        self.ledger = ledger
        self.calendar = calendar
        self.situation = situation
        self.engineer = engineer
        self.gateway = gateway
        self.state_engine = state_engine
        self.advisories = advisories
        self.learning = None                  # Learning (engagement, preferences, normals), when wired
        self.owner_cost = _env_float("ARVIS_OPS_OWNER_COST", 1000.0)
        self.max_per_hour = int(_env_float("ARVIS_OPS_MAX_PER_HOUR", 4))
        self.ack_min = _env_float("ARVIS_OPS_ACK_MIN", 15.0)
        self.settle_min = _env_float("ARVIS_OPS_ALARM_SETTLE_MIN", 10.0)
        self.hold_min = _env_float("ARVIS_OPS_CONVERSATION_HOLD_MIN", 5.0)
        self.brief_hour = int(_env_float("ARVIS_OPS_BRIEF_HOUR", 7))
        self._queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: set = set()

    # ── intake ────────────────────────────────────────────────────────────
    def attach(self, event_bus: Any) -> None:
        for event_type in NORMALISERS:
            event_bus.subscribe(event_type, self._on_event)

    def _on_event(self, event: Dict[str, Any]) -> None:
        """Bus callback (may run off the event loop): hand to the single worker."""
        if self._queue is not None and self._loop is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is self._loop:
                self._queue.put_nowait(event)
            else:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
            return
        try:                                            # no worker yet: handle inline on the loop
            task = asyncio.get_running_loop().create_task(self.handle_event(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except RuntimeError:
            logger.error(f"[Gate] {event.get('type')} received with no event loop — dropped")

    async def handle_event(self, event: Dict[str, Any]) -> None:
        for s in to_signals(event):
            try:
                await self.process(s)
            except Exception as e:
                logger.error(f"[Gate] processing {s.topic} failed: {type(e).__name__}: {e}", exc_info=True)

    # ── deciding ──────────────────────────────────────────────────────────
    def audience(self, s: Signal) -> List[Person]:
        if s.audience:
            return [p for p in (self.people.get(n) for n in s.audience) if p]
        out = list(self.people.by_role("fm"))
        if (s.safety or s.severity == "critical" or s.kind == "monitoring"
                or (s.cost is not None and s.cost >= self.owner_cost)):
            out += self.people.by_role("owner")
        if s.kind == "fdd_fix":
            note = str(s.ref.get("note") or "")
            out += [p for p in self.people.by_role("technician") if p.name and p.name in note]
        return out

    async def decide(self, s: Signal, person: Person, now: datetime, rec: Dict[str, Any]) -> Decision:
        prev = (rec or {}).get("previous")
        if await self.store.told(person.number, s.topic):
            recurred = bool(prev and prev.get("state") == "resolved")
            worse = bool(prev and SEVERITIES.index(s.severity) > SEVERITIES.index(prev.get("severity") or "info"))
            if not (recurred or worse):
                return Decision("DROP").because("already_told", s.topic)

        critical = s.safety or s.severity == "critical"
        if critical:
            d = Decision("NOW").because("safety" if s.safety else "critical", s.title)
        elif s.severity == "high":
            d = Decision("NOW").because("high", s.title)
        elif s.severity == "medium":
            d = Decision("SOON").because("medium", s.title)
        else:
            d = Decision("DIGEST").because(s.severity, s.title)

        if s.llm_origin and d.level == "NOW":
            backing = await self.ledger.open_on(s.subject, ("alarm", "fdd_fault"))
            if not backing:
                d.level = "SOON"
                critical = False                     # an unbacked LLM "critical" must not break quiet hours either
                d.because("llm_uncorroborated", "an LLM conclusion with no open alarm or confirmed fault behind it")

        if self.calendar.quiet(now) and not critical and d.level in ("NOW", "SOON"):
            d.level = "DIGEST"
            d.because("quiet_hours", self.calendar.describe(now))
        elif not self.calendar.occupied(now) and not critical:
            if d.level == "NOW":
                d.level = "SOON"
                d.because("unoccupied", self.calendar.describe(now))
            elif d.level == "SOON" and s.severity == "medium":
                d.level = "DIGEST"
                d.because("unoccupied", self.calendar.describe(now))

        if not s.safety and d.level in ("NOW", "SOON"):
            handled = await self.situation.handling(s.subject, person.number)
            if handled:
                d.level = _down(d.level)
                d.because("already_handled", "; ".join(handled))

        if self.learning is not None and not s.safety and d.level != "DROP":
            pref = await self.learning.preference_for(person.number, s.kind, s.subject)
            if pref and pref["mode"] == "mute":
                d.level = "DROP"
                return d.because("muted_by_person", pref.get("said") or f"{pref['scope_kind']} {pref['scope_value']}")
            if pref and pref["mode"] == "digest" and d.level in ("NOW", "SOON"):
                d.level = "DIGEST"
                d.because("digest_by_person", pref.get("said") or f"{pref['scope_kind']} {pref['scope_value']}")
            local = self.calendar.local(now)
            normal = await self.learning.normal_for(s.kind, s.subject, self.calendar.day_type(now), local.hour)
            if normal:
                d.level = "DROP"
                return d.because("learned_normal", f"#{normal['id']} {normal['hours']}")
            if d.level in ("NOW", "SOON"):
                e = await self.learning.engagement(person.number, s.kind)
                if e["n"] >= 5 and e["p"] < 0.25:
                    d.level = _down(d.level)
                    d.because("low_engagement", f"{person.first_name} engaged with {e['engaged']} of {e['n']} "
                                                f"'{s.kind}' messages lately")

        if not s.safety and d.level in ("NOW", "SOON"):
            if await self.store.proactive_count(person.number, 1.0) >= self.max_per_hour:
                d.level = "DIGEST"
                d.because("hourly_cap", f"{self.max_per_hour} unprompted messages in the last hour")
        return d

    async def process(self, s: Signal, now: Optional[datetime] = None) -> Dict[str, Decision]:
        now = now or utcnow()
        rec = await self.ledger.upsert(s, now)
        if s.clears:
            return await self._clear(s, now)
        decisions: Dict[str, Decision] = {}
        for person in self.audience(s):
            d = await self.decide(s, person, now, rec)
            await self.ledger.record_decision(s, person.number, d.level, d.reasons, now)
            decisions[person.number] = d
            await self._act(s, person, d, now)
        return decisions

    async def _clear(self, s: Signal, now: datetime) -> Dict[str, Decision]:
        await self.ledger.resolve(s.clears, now)
        told = [p for p in self.people.by_role("fm", "owner", "technician")
                if await self.store.told(p.number, s.clears)]
        await self.store.forget_topic(s.clears)            # if it comes back, it is news again
        decisions: Dict[str, Decision] = {}
        for person in told:
            d = Decision("DIGEST" if self.calendar.quiet(now) else "SOON").because("cleared", s.clears)
            await self.ledger.record_decision(s, person.number, d.level, d.reasons, now)
            decisions[person.number] = d
            await self._act(s, person, d, now)
        if not told:
            logger.info(f"[Gate] {s.clears} cleared before anyone was told — nothing to say")
        return decisions

    # ── acting ────────────────────────────────────────────────────────────
    def _purpose(self, s: Signal, person: Person) -> str:
        if s.clears or s.kind.endswith("cleared") or s.kind == "monitoring_restored":
            return "tell them it is back to normal"
        if s.kind == "fdd_fault" and person.role == "owner":
            return "let them know about a costly problem the team is now handling, in business terms"
        return _PURPOSE.get(s.kind, "tell them what happened and what you would do next")

    @staticmethod
    def _safety_text(s: Signal) -> str:
        return f"⚠️ {s.title}\n{s.facts}\nTell me as soon as someone is on it."

    async def _act(self, s: Signal, person: Person, d: Decision, now: datetime) -> None:
        if d.level == "DROP":
            return
        if d.level == "NOW":
            text = self._safety_text(s) if s.safety else await self.engineer.compose(person, s.facts,
                                                                                     self._purpose(s, person))
            msg_id = await self.gateway.send(person, text, kind="proactive")
            if msg_id is None:                          # not delivered: keep it, retry from the queue
                await self.ledger.enqueue(s, person.number, "SOON", now + timedelta(minutes=1), now)
                return
            await self.store.mark_told(person.number, s.topic, s.title)
            await self._delivered(person, s.topic, s.kind, s.subject, msg_id, now)
            # Chase for an acknowledgement only where a person is needed now: safety,
            # critical, high alarms, losing sight of the building. A costly energy fault
            # is important but not something to escalate every 15 minutes.
            needs_ack = (s.safety or s.severity == "critical"
                         or (s.kind in ("alarm", "monitoring") and s.severity == "high"))
            if needs_ack:
                await self.ledger.add_alert(s.topic, person.number, msg_id, now)
                row = await self.ledger.get(s.topic)
                if row and row.get("ladder_level", -1) < 0:
                    await self.ledger.set_ladder(s.topic, 0, now + timedelta(minutes=self.ack_min))
            return
        if d.level == "SOON":
            due = now
            if s.kind == "alarm" and s.severity not in ("critical",) and not s.safety:
                due = now + timedelta(minutes=self.settle_min)   # see if it clears by itself first
            await self.ledger.enqueue(s, person.number, "SOON", due, now)
            return
        brief = self.calendar.next_hour(self.brief_hour, now)
        await self.ledger.enqueue(s, person.number, "DIGEST", brief, now)

    async def _delivered(self, person: Person, topic: str, kind: str, subject: Optional[str],
                         message_id: Optional[str], now: datetime) -> None:
        if self.learning is None or kind.endswith(("cleared", "restored")):
            return
        try:
            await self.learning.record_delivery(person.number, topic, kind, subject, message_id,
                                                self.calendar.day_type(now), self.calendar.local(now).hour)
        except Exception as e:
            logger.warning(f"[Gate] engagement record failed: {e}")

    # ── acknowledgement ───────────────────────────────────────────────────
    async def acknowledge(self, topic: str, person: Person, note: str = "", now: Optional[datetime] = None) -> bool:
        now = now or utcnow()
        row = await self.ledger.get(topic)
        if row is None:
            return False
        ok = await self.ledger.acknowledge(topic, f"whatsapp:{person.name}", now)
        ref = row.get("ref") or {}
        if ref.get("alarm_id") and self.state_engine is not None:
            try:
                await self.state_engine.acknowledge_alarm(ref["alarm_id"], by=f"whatsapp:{person.name}",
                                                          note=note or None)
            except Exception as e:
                logger.warning(f"[Gate] alarm ack for {ref['alarm_id']} failed: {e}")
        if ref.get("advisory_id") and self.advisories is not None and hasattr(self.advisories, "acknowledge"):
            try:
                await self.advisories.acknowledge(ref["advisory_id"], f"whatsapp:{person.name}", note or "")
            except Exception as e:
                logger.warning(f"[Gate] advisory ack for {ref['advisory_id']} failed: {e}")
        return ok

    # ── the clock: flush SOON, escalate unacknowledged ────────────────────
    async def tick(self, now: Optional[datetime] = None) -> None:
        now = now or utcnow()
        await self._flush_soon(now)
        await self._escalate(now)
        if self.situation is not None and getattr(self.situation, "field_checks", None) is not None:
            await self.situation.field_checks.list_checks()        # lets overdue checks expire (and be reported)

    async def _flush_soon(self, now: datetime) -> None:
        items = await self.ledger.due(now, level="SOON")
        by_person: Dict[str, list] = {}
        for it in items:
            by_person.setdefault(it.number, []).append(it)
        for number, its in by_person.items():
            person = self.people.get(number)
            if person is None:
                await self.ledger.mark([i.id for i in its], "cancelled", now)
                continue
            if await self.situation.in_conversation(number, self.hold_min):
                continue                                         # wait until they've finished talking
            live = []
            for it in its:                                       # re-check: cleared while waiting?
                row = await self.ledger.get(it.topic)
                if row and row.get("state") == "resolved" and not it.kind.endswith(("cleared", "restored")):
                    await self.ledger.mark([it.id], "cancelled", now)
                else:
                    live.append(it)
            if not live:
                continue
            if len(live) == 1:
                it = live[0]
                fake = Signal(kind=it.kind, topic=it.topic, title=it.title, facts=it.facts)
                text = await self.engineer.compose(person, it.facts, self._purpose(fake, person))
            else:
                facts = "\n\n".join(f"- {it.title}: {it.facts}" for it in live)
                text = await self.engineer.compose(person, facts, f"tell them about these {len(live)} things in one "
                                                                  "message, most important first")
            if await self.gateway.send(person, text, kind="proactive") is None:
                await self.ledger.mark([i.id for i in live], "retry", now)
                for it in live:
                    if it.attempts + 1 >= 5:
                        await self.ledger.mark([it.id], "failed", now)
                        logger.error(f"[Gate] giving up on {it.topic} for {person.name} after 5 attempts")
                continue
            await self.ledger.mark([i.id for i in live], "sent", now)
            for it in live:
                await self.store.mark_told(number, it.topic, it.title)
                row = await self.ledger.get(it.topic)
                await self._delivered(person, it.topic, it.kind, (row or {}).get("subject"), None, now)

    async def _authoritative_state(self, row: Dict[str, Any]) -> Optional[str]:
        """Acknowledged or cleared somewhere else (dashboard, the BMS)? Then stop chasing."""
        alarm_id = (row.get("ref") or {}).get("alarm_id")
        if alarm_id and self.state_engine is not None:
            a = (getattr(self.state_engine, "_alarms", {}) or {}).get(alarm_id)
            if a is not None:
                st = getattr(a.state, "value", str(a.state)).lower()
                if st in ("acknowledged", "resolved"):
                    return st
        return None

    async def _escalate(self, now: datetime) -> None:
        for row in await self.ledger.ladder_due(now):
            if row is None:
                continue
            elsewhere = await self._authoritative_state(row)
            if elsewhere:
                if elsewhere == "resolved":
                    await self.ledger.resolve(row["topic"], now)
                else:
                    await self.ledger.acknowledge(row["topic"], "elsewhere", now)
                continue
            level = int(row.get("ladder_level") or 0) + 1
            critical = bool(row.get("safety")) or row.get("severity") == "critical"
            if self.calendar.quiet(now) and not critical:
                await self.ledger.set_ladder(row["topic"], level - 1, None)   # not worth waking anyone
                continue
            fms, owners = self.people.by_role("fm"), self.people.by_role("owner")
            targets = fms if level == 1 else (owners if level == 2 else [])
            if not targets:
                await self.ledger.set_ladder(row["topic"], level, None)
                continue
            minutes = round(self.ack_min * level)
            text = (f"Still nobody on this after {minutes} min: {row['title']}\n{row['facts']}\n"
                    "Tell me as soon as someone is on it.")
            sig = Signal(kind=row["kind"], topic=row["topic"], title=row["title"], facts=row["facts"],
                         severity=row["severity"], subject=row["subject"])
            for p in targets:
                await self.ledger.record_decision(sig, p.number, "NOW",
                                                  [{"code": "escalation", "detail": f"level {level}, "
                                                                                    f"unacknowledged {minutes} min"}],
                                                  now)
                msg_id = await self.gateway.send(p, text, kind="proactive")
                if msg_id is not None:
                    await self.ledger.add_alert(row["topic"], p.number, msg_id, now)
                    await self.store.mark_told(p.number, row["topic"], row["title"])
            nxt = now + timedelta(minutes=self.ack_min) if level < 2 else None
            await self.ledger.set_ladder(row["topic"], level, nxt)

    async def run(self, tick_seconds: float = 60.0) -> None:
        """The gate's worker (serialises event handling) and its clock."""
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

        async def worker():
            while True:
                event = await self._queue.get()
                await self.handle_event(event)

        w = self._loop.create_task(worker())
        try:
            while True:
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[Gate] tick failed: {type(e).__name__}: {e}", exc_info=True)
                await asyncio.sleep(tick_seconds)
        finally:
            w.cancel()
