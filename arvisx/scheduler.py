"""
ArvisX — the heartbeat: make ArvisX run its own checks on a cadence, autonomously.

`monitor`, `evaluate_ops_readiness`, alert dispatch are all call-driven today — something
external has to poke them. The Heartbeat turns ArvisX into a standing process: on each
tick it refreshes state, runs a monitor sweep (rules-first, agent on escalation), and —
for any building still LEARNING — re-checks baseline readiness so it goes operational the
moment it's confident (or keeps extending). Read-only: it observes and advises, never acts.

`Heartbeat` is a tiny, testable loop primitive (inject the tick fn, cap ticks, stop event).
`community_tick` is the ArvisX-specific body. Wire the loop into the API at startup
(ARVISX_HEARTBEAT=1) or run it from a script/cron.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("arvisx.scheduler")

TickFn = Callable[[int], Awaitable[Any]]


class Heartbeat:
    """Run an async tick on a fixed interval until stopped / tick-capped."""

    def __init__(self, on_tick: TickFn, interval_s: float = 300.0):
        self.on_tick = on_tick
        self.interval_s = float(interval_s)
        self._stop = asyncio.Event()
        self.ticks = 0

    def stop(self):
        self._stop.set()

    async def run(self, max_ticks: Optional[int] = None):
        """Loop: tick, then sleep interval (interruptible by stop()). Returns tick count."""
        while not self._stop.is_set():
            self.ticks += 1
            try:
                await self.on_tick(self.ticks)
            except Exception as e:
                logger.warning(f"[heartbeat] tick {self.ticks} failed: {e}")
            if max_ticks is not None and self.ticks >= max_ticks:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass
        return self.ticks


async def community_tick(state, llm=None, max_investigations: int = 3) -> Dict[str, Any]:
    """One ArvisX heartbeat over a community `state` (the API's _State or equivalent):
    refresh → monitor sweep (escalation-aware) → readiness re-check for LEARNING buildings.
    Returns a summary of what it found/decided this tick."""
    from arvisx.agent import monitor
    from arvisx.simulator import community_zones

    rep = state.report_now()
    zones = community_zones("healthy" if getattr(state, "scenario", "prd") == "healthy" else "prd")
    invs = await monitor(state.current_assets(), rep.risks, llm=llm, db=getattr(state, "db", None),
                         baselines=getattr(state, "baselines", None),
                         skillbook=getattr(state, "skillbook", None),
                         max_investigations=max_investigations, store=getattr(state, "store", None),
                         zones=zones, wo_store=getattr(state, "wo_store", None))

    # Durable agent state: persist each investigation this tick produced.
    db = getattr(state, "db", None)
    if db is not None:
        from dataclasses import asdict
        for inv in invs:
            try:
                db.save_investigation(inv.asset_id, inv.trigger, inv.root_cause,
                                      inv.recommended_action, inv.confidence_band, inv.source, asdict(inv))
            except Exception as e:
                logger.warning(f"[heartbeat] persist investigation failed: {e}")

    # Checklist sweeps — round reminders/lapse + issue-SLA escalation, per building.
    # Runs on the heartbeat so chasing advances even if the WhatsApp bot is down
    # (notifications queue persistently and deliver when the bot is back).
    if db is not None:
        try:
            from arvisx import checklist_intel as ci
            from arvisx.sla import run_escalations
            for b in db.checklist_buildings():
                ci.lapse_stale_rounds(db, b)
                ci.round_reminders(db, b)
                run_escalations(db, b)
        except Exception as e:
            logger.warning(f"[heartbeat] checklist sweep failed: {e}")

    readiness: List[Dict[str, Any]] = []
    commissioner = getattr(state, "commissioner", None)
    if commissioner is not None:
        for b in commissioner.list():
            if b.get("state") == "learning":
                try:
                    readiness.append(commissioner.evaluate_ops_readiness(
                        b["building_id"], state.current_assets(), state.baselines))
                except Exception as e:
                    logger.warning(f"[heartbeat] readiness check {b['building_id']} failed: {e}")

    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "readiness": round(rep.readiness, 1),
               "risks": len(rep.risks), "investigated": len(invs),
               "escalated": sum(1 for i in invs if getattr(i, "source", "").startswith("agent")),
               "learning_checks": readiness}
    if db is not None:
        try:
            db.save_tick(summary)
        except Exception as e:
            logger.warning(f"[heartbeat] persist tick failed: {e}")
    return summary
