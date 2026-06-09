"""
Watch Manager — agent-decided temporal observation (wake / sleep / re-investigate).

The AnomalyWatchdog + InvestigationDispatcher react to events with a suppression
cooldown. What they LACK is an agent-chosen OBSERVATION WINDOW: "this needs watching
over time — recheck in ~N, but wake sooner if the value moves." This adds exactly that,
ported from the residential ArvisX WatchAgent and adapted to the commercial BMS (polls
bms_state for change since there is no telemetry update-callback here).

Use cases this unlocks:
  • DRIFT CONFIRMATION   — don't escalate a sub-critical deviation until it's SUSTAINED
                           over a chosen window (kills nuisance alarms on transients).
  • POST-MAINTENANCE     — auto-recheck N hours after a work order closes: did the fix hold?
  • SLOW-FAULT TRACKING  — watch a creeping bearing/filter/coil over hours/days.

On each wake the manager re-invokes a caller-supplied `on_recheck` (typically a swarm
investigation) which returns ("resolved", result) or ("wait", new_seconds). Read-only:
it observes and re-investigates; it never actuates. Bounded by max_cycles / wall clock.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger("arvis.monitoring.watch")


@dataclass
class Watch:
    equipment_id: str
    point_id: str
    reason: str
    est_seconds: float
    created_at: datetime
    wake_at: datetime
    kind: str = "observe"                 # drift_confirm | post_maintenance | observe
    baseline_value: Any = None            # point value at schedule time (change detection)
    resolved: bool = False
    result: Any = None
    checks: int = 0
    woke_on: List[str] = field(default_factory=list)   # "change" | "timeout" per cycle
    watch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_record(self) -> dict:
        return {"watch_id": self.watch_id, "equipment_id": self.equipment_id,
                "point_id": self.point_id, "reason": self.reason, "kind": self.kind,
                "est_seconds": self.est_seconds, "created_at": self.created_at.isoformat(),
                "wake_at": self.wake_at.isoformat(), "resolved": self.resolved,
                "checks": self.checks, "woke_on": list(self.woke_on), "result": self.result}


# on_recheck(watch, changed, due) -> ("resolved", result) | ("wait", new_seconds)
CheckFn = Callable[[Watch, bool, bool], Awaitable[tuple]]


class WatchManager:
    """Holds active watches and runs the sleep/wake loop against the live bms_state."""

    def __init__(self, bms_state=None, db=None):
        self.bms_state = bms_state
        self.db = db                       # optional: durable watch persistence
        self.watches: List[Watch] = []
        self._stop = asyncio.Event()

    async def _point_value(self, equipment_id: str, point_id: str):
        if not self.bms_state:
            return None
        try:
            points = await self.bms_state.get_points_by_equipment(equipment_id)
            for p in points:
                if getattr(p, "point_id", None) == point_id:
                    return getattr(p, "value", None)
        except Exception as e:
            logger.debug(f"[watch] read {equipment_id}/{point_id} failed: {e}")
        return None

    def _persist(self, w: Watch):
        if self.db is not None and hasattr(self.db, "save_watch"):
            try:
                self.db.save_watch(w.to_record())
            except Exception as e:
                logger.debug(f"[watch] persist failed: {e}")

    async def schedule(self, equipment_id: str, point_id: str, reason: str,
                       est_seconds: float, kind: str = "observe") -> Watch:
        now = datetime.now()
        w = Watch(equipment_id=equipment_id, point_id=point_id, reason=reason,
                  est_seconds=float(est_seconds), created_at=now,
                  wake_at=now + timedelta(seconds=float(est_seconds)), kind=kind,
                  baseline_value=await self._point_value(equipment_id, point_id))
        self.watches.append(w)
        self._persist(w)
        logger.info(f"[watch] scheduled {kind} {equipment_id}/{point_id} "
                    f"est={est_seconds:.0f}s — {reason}")
        return w

    def stop(self):
        self._stop.set()

    async def run(self, on_recheck: CheckFn, max_cycles: int = 24,
                  max_wall_seconds: float = 86400.0, poll_cap_seconds: float = 900.0) -> List[Watch]:
        """Sleep until the nearest deadline (capped), wake, and for each due/changed watch
        call on_recheck → resolve or reschedule. Returns the watches when all resolve or
        budgets exhaust."""
        start = datetime.now()
        cycles = 0
        while any(not w.resolved for w in self.watches) and cycles < max_cycles:
            if self._stop.is_set() or (datetime.now() - start).total_seconds() >= max_wall_seconds:
                break
            cycles += 1
            pending = [w for w in self.watches if not w.resolved]
            now = datetime.now()
            sleep_s = min((w.wake_at - now).total_seconds() for w in pending)
            sleep_s = max(0.0, min(sleep_s, poll_cap_seconds))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(sleep_s, 0.0) or 0.05)
                break  # stop() fired
            except asyncio.TimeoutError:
                pass

            now = datetime.now()
            for w in pending:
                cur = await self._point_value(w.equipment_id, w.point_id)
                changed = cur is not None and cur != w.baseline_value
                due = now >= w.wake_at
                if not (changed or due):
                    continue
                w.checks += 1
                w.woke_on.append("change" if changed else "timeout")
                kind, payload = await on_recheck(w, changed, due)
                if kind == "resolved":
                    w.resolved, w.result = True, payload
                    logger.info(f"[watch] resolved {w.equipment_id}/{w.point_id} "
                                f"after {w.checks} check(s)")
                else:
                    w.est_seconds = float(payload)
                    w.wake_at = now + timedelta(seconds=float(payload))
                    w.baseline_value = cur
                self._persist(w)
        return self.watches

    def open_watches(self) -> List[dict]:
        return [w.to_record() for w in self.watches if not w.resolved]
