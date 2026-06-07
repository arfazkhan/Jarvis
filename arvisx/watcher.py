"""
ArvisX Phase-12c — the active-monitoring watcher (sleep / wake / re-think).

A rule-based monitor polls on a fixed timer. An AGENT decides: "this needs to be
observed over time — recheck in ~N minutes, but wake me sooner if the signal moves."
This implements exactly that. When investigation can't conclude immediately (a tank
must refill, a creep must prove sustained, a fire test must be performed), the agent
schedules a WATCH with an estimated duration; the WatchAgent then SLEEPS until either:
  • a relevant telemetry update arrives (AssetStore fires its update callback), or
  • the estimated deadline elapses,
whichever comes first — then re-invokes the investigation with fresh state and either
RESOLVES or reschedules with a new estimate. Bounded by max_cycles / wall clock so cost
stays finite. Still read-only: it observes and concludes, never actuates.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger("arvisx.watcher")


@dataclass
class Watch:
    asset_id: str
    signal: str
    reason: str
    est_seconds: float
    created_at: datetime
    wake_at: datetime
    baseline_ts: Optional[datetime]          # signal's last-update ts when scheduled
    resolved: bool = False
    result: Any = None
    woke_on: List[str] = field(default_factory=list)   # "update" | "timeout" per cycle
    checks: int = 0


# on_check(watch, woke_on_update, due) -> ("resolved", result) | ("wait", new_est_seconds)
CheckFn = Callable[[Watch, bool, bool], Awaitable[tuple]]


class WatchAgent:
    """Holds active watches and runs the sleep/wake loop against a live AssetStore."""

    def __init__(self, store):
        self.store = store
        self.watches: List[Watch] = []
        self._event: Optional[asyncio.Event] = None

    def _ensure_event(self):
        if self._event is None:
            self._event = asyncio.Event()
            loop = asyncio.get_event_loop()
            ev = self._event

            def _cb(_aid, _sig):
                loop.call_soon_threadsafe(ev.set)

            self.store.set_update_callback(_cb)

    def schedule(self, asset_id: str, signal: str, reason: str, est_seconds: float) -> Watch:
        now = datetime.now()
        w = Watch(asset_id=asset_id, signal=signal, reason=reason, est_seconds=float(est_seconds),
                  created_at=now, wake_at=now + timedelta(seconds=float(est_seconds)),
                  baseline_ts=self.store.signal_ts(asset_id, signal))
        self.watches.append(w)
        logger.info(f"[watch] scheduled {asset_id}.{signal} est={est_seconds}s — {reason}")
        return w

    async def run(self, on_check: CheckFn, max_cycles: int = 12,
                  max_wall_seconds: float = 3600.0, poll_cap_seconds: float = 300.0) -> List[Watch]:
        """Sleep/wake until all watches resolve or budgets exhaust. `on_check` re-evaluates
        a due/triggered watch and decides resolve-vs-keep-waiting."""
        self._ensure_event()
        start = datetime.now()
        cycles = 0
        while any(not w.resolved for w in self.watches) and cycles < max_cycles:
            if (datetime.now() - start).total_seconds() >= max_wall_seconds:
                break
            cycles += 1
            pending = [w for w in self.watches if not w.resolved]
            now = datetime.now()
            sleep_s = min((w.wake_at - now).total_seconds() for w in pending)
            sleep_s = max(0.0, min(sleep_s, poll_cap_seconds))

            self._event.clear()
            woke_on_update = True
            try:
                await asyncio.wait_for(self._event.wait(), timeout=max(sleep_s, 0.0) or 0.001)
            except asyncio.TimeoutError:
                woke_on_update = False

            now = datetime.now()
            for w in pending:
                changed = self.store.signal_ts(w.asset_id, w.signal) != w.baseline_ts
                due = now >= w.wake_at
                if not (changed or due):
                    continue
                w.checks += 1
                w.woke_on.append("update" if changed else "timeout")
                kind, payload = await on_check(w, changed, due)
                if kind == "resolved":
                    w.resolved, w.result = True, payload
                    logger.info(f"[watch] resolved {w.asset_id}.{w.signal} after {w.checks} check(s)")
                else:
                    w.est_seconds = float(payload)
                    w.wake_at = now + timedelta(seconds=float(payload))
                    w.baseline_ts = self.store.signal_ts(w.asset_id, w.signal)
        return self.watches
