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

When a watch's window is up the manager calls a caller-supplied `on_recheck` (the
dispatcher decides from evidence — e.g. did the anomaly repeat?) which returns
("resolved", result) or ("wait", new_seconds). Read-only: it observes and
re-investigates; it never actuates. Runs for the life of the process.
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
        self._added = asyncio.Event()          # wakes the loop when a watch is scheduled

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
        self._added.set()
        logger.info(f"[watch] scheduled {kind} {equipment_id}/{point_id} "
                    f"est={est_seconds:.0f}s — {reason}")
        return w

    def stop(self):
        self._stop.set()
        self._added.set()

    async def run(self, on_recheck: CheckFn, poll_cap_seconds: float = 900.0) -> None:
        """Service loop for the life of the process: sleep until the nearest watch is due
        (or a new watch arrives, or stop()), then hand each due watch to on_recheck →
        resolve or reschedule.

        (It used to return as soon as there were no open watches — and it was started at
        boot, when there are none — so watches scheduled later were never checked. It
        also woke on any change of a float reading, i.e. on almost every poll; a watch
        now wakes when its window is up, and the caller decides with real evidence.)"""
        while not self._stop.is_set():
            pending = [w for w in self.watches if not w.resolved]
            if pending:
                now = datetime.now()
                sleep_s = min((w.wake_at - now).total_seconds() for w in pending)
                sleep_s = max(0.05, min(sleep_s, poll_cap_seconds))
            else:
                sleep_s = poll_cap_seconds
            self._added.clear()
            try:
                await asyncio.wait_for(self._added.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            now = datetime.now()
            for w in [w for w in self.watches if not w.resolved and now >= w.wake_at]:
                w.checks += 1
                w.woke_on.append("timeout")
                try:
                    kind, payload = await on_recheck(w, False, True)
                except Exception as e:
                    logger.error(f"[watch] re-check of {w.equipment_id}/{w.point_id} failed: {e}")
                    kind, payload = "resolved", {"error": f"{type(e).__name__}: {e}"}
                if kind == "resolved":
                    w.resolved, w.result = True, payload
                    logger.info(f"[watch] resolved {w.equipment_id}/{w.point_id} after {w.checks} check(s)")
                else:
                    w.est_seconds = float(payload)
                    w.wake_at = now + timedelta(seconds=float(payload))
                self._persist(w)
            # Resolved watches only need keeping for a while (open_watches/history).
            if len(self.watches) > 500:
                self.watches = [w for w in self.watches if not w.resolved] +                                [w for w in self.watches if w.resolved][-100:]

    def open_watches(self) -> List[dict]:
        return [w.to_record() for w in self.watches if not w.resolved]
