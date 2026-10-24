"""
Is ARVIS still seeing the building?
===================================

A dead BMS link, a crashed gateway or a stopped poller used to produce silence:
the watchdog and the telemetry recorder skip stale points, adapters only logged,
and ``data_source`` never went back from LIVE. A building engineer who loses
sight of the plant says so — this module does.

  assess_monitoring(ops)        one definition of "fresh data" (also used by /health)
  MonitoringHealthWatcher       every ARVIS_HEALTH_CHECK_S (60 s):
      blind     no fresh reading for ARVIS_BLIND_AFTER_MIN (10), or every required
                source disconnected — after hysteresis → "monitoring_blind"
      degraded  more than ARVIS_DEGRADED_STALE_FRAC (25 %) of points stale, a device
                missing, or an optional source down → "monitoring_degraded"
      restored  two healthy checks in a row after blind/degraded → "monitoring_restored"
  It also keeps ``ops.data_source`` honest: LIVE ↔ UNAVAILABLE.

Simulator mode is not watched (there is nothing real to lose sight of).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arvis.monitoring.health")

_ADAPTERS = ("bacnet_adapter", "modbus_adapter", "opcua_adapter")
_LIVE_MODES = ("bacnet", "modbus", "opcua", "multi")


def _source_stats(ops: Any) -> List[Dict[str, Any]]:
    """Every live source's own stats: from the source manager (all sources, with
    their id and whether they are required), else the three legacy adapter slots."""
    mgr = getattr(ops, "source_manager", None)
    if mgr is not None and getattr(mgr, "handles", None):
        return mgr.stats()
    out = []
    for name in _ADAPTERS:
        ad = getattr(ops, name, None)
        if ad is None or not hasattr(ad, "get_stats"):
            continue
        try:
            st = ad.get_stats()
        except Exception as e:
            st = {"error": f"{type(e).__name__}: {e}"}
        kind = name.replace("_adapter", "")
        out.append({"id": kind, "kind": kind, "required": True, **st})
    return out


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _aware(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, datetime):
        return None
    return ts if ts.tzinfo is not None else ts.astimezone()      # naive = this process's local clock


def assess_monitoring(ops: Any, fresh_minutes: float = 15.0, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Fresh points (a reading within `fresh_minutes`), total points, and each live
    adapter's own view (connected, stale points, missing devices, polling)."""
    now = now or datetime.now(timezone.utc)
    state = getattr(ops, "state_engine", None)
    points = getattr(state, "_points", {}) or {}
    window = timedelta(minutes=fresh_minutes)
    fresh = 0
    for p in list(points.values()):
        ts = _aware(getattr(p, "timestamp", None))
        if ts is not None and now - ts <= window:
            fresh += 1
    adapters: List[Dict[str, Any]] = []
    for st in _source_stats(ops):
        adapters.append({
            "adapter": st["kind"], "id": st["id"], "required": bool(st.get("required", True)),
            "connected": bool(st.get("is_connected", st.get("connected", False))),
            "polling": bool(st.get("polling_active", st.get("polling", False))),
            "stale_points": len(st.get("stale_points") or []),
            "devices_missing": list(st.get("devices_missing") or st.get("missing_devices") or []),
        })
    total = len(points)
    return {"total_points": total, "fresh_points": fresh, "fresh_minutes": fresh_minutes,
            "fresh_ratio": round(fresh / total, 3) if total else 0.0, "adapters": adapters}


class MonitoringHealthWatcher:
    def __init__(self, ops: Any, publish: Callable[[str, Dict[str, Any]], None]):
        self.ops = ops
        self.publish = publish
        self.interval = _env_float("ARVIS_HEALTH_CHECK_S", 60.0)
        self.fresh_minutes = _env_float("ARVIS_BLIND_AFTER_MIN", 10.0)
        self.confirm_s = _env_float("ARVIS_BLIND_CONFIRM_S", 180.0)        # hysteresis before alerting
        self.restore_checks = int(_env_float("ARVIS_RESTORE_CHECKS", 2))
        self.degraded_frac = _env_float("ARVIS_DEGRADED_STALE_FRAC", 0.25)
        self.state = "unknown"                   # unknown | ok | degraded | blind
        self.bad_since: Optional[datetime] = None
        self.bad_kind: Optional[str] = None
        self.ok_streak = 0
        self.alert_started: Optional[datetime] = None
        self.last: Dict[str, Any] = {}

    def _live(self) -> bool:
        return getattr(self.ops, "mode", None) in _LIVE_MODES

    def _classify(self, a: Dict[str, Any]) -> str:
        live = a["adapters"]
        if a["total_points"] == 0 and not live:
            return "unknown"                     # nothing configured to watch
        required = [x for x in live if x["required"]] or live
        if a["fresh_points"] == 0 or (required and not any(x["connected"] for x in required)):
            return "blind"
        if any(not x["connected"] for x in live):
            return "degraded"                    # an optional source is down; the rest still see
        stale = sum(x["stale_points"] for x in live)
        if a["total_points"] and stale / a["total_points"] > self.degraded_frac:
            return "degraded"
        if any(x["devices_missing"] for x in live):
            return "degraded"
        return "ok"

    def check_once(self, now: Optional[datetime] = None) -> Optional[str]:
        """One assessment. Returns the event published, if any."""
        if not self._live():
            return None
        now = now or datetime.now(timezone.utc)
        a = assess_monitoring(self.ops, self.fresh_minutes, now)
        self.last = a
        kind = self._classify(a)
        if kind == "unknown":
            return None

        if kind == "ok":
            self.bad_since, self.bad_kind = None, None
            self.ok_streak += 1
            if self.state in ("blind", "degraded") and self.ok_streak >= self.restore_checks:
                was, started = self.state, self.alert_started
                self.state, self.alert_started = "ok", None
                if getattr(self.ops, "data_source", None) == "UNAVAILABLE":
                    self.ops.data_source = "LIVE"
                minutes = round((now - started).total_seconds() / 60) if started else None
                self.publish("monitoring_restored", {"was": was, "minutes": minutes, "at": now.isoformat(),
                                                     "assessment": a})
                logger.warning(f"[Health] monitoring restored after {minutes} min ({was})")
                return "monitoring_restored"
            if self.state == "unknown":
                self.state = "ok"
            return None

        self.ok_streak = 0
        if self.bad_kind != kind:
            self.bad_since, self.bad_kind = now, kind
        if self.state == kind or (now - self.bad_since).total_seconds() < self.confirm_s:
            return None                          # already announced, or not confirmed yet
        if self.state == "blind" and kind == "degraded":
            return None                          # partial recovery is not "restored"; wait for ok
        self.state = kind
        self.alert_started = self.alert_started or self.bad_since
        if kind == "blind" and getattr(self.ops, "data_source", None) == "LIVE":
            self.ops.data_source = "UNAVAILABLE"
        event = f"monitoring_{kind}"
        self.publish(event, {"since": self.bad_since.isoformat(), "assessment": a})
        logger.warning(f"[Health] {event}: {a['fresh_points']}/{a['total_points']} points fresh, "
                       f"adapters={a['adapters']}")
        return event

    async def run(self) -> None:
        while True:
            try:
                self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Health] check failed: {e}")
            await asyncio.sleep(self.interval)
