"""
Investigation Dispatcher
========================

Converts anomaly events (from AnomalyWatchdog) and alarm callbacks into
autonomous Queen swarm investigations. Publishes each conclusion on the event bus
("investigation_concluded" — the WhatsApp engineer decides who needs to know) and
to the dashboard's SSE "monitor" channel. Archives to episodic memory.

Subscribes to EventBus "anomaly_detected" events.
Also accepts direct alarm callbacks for critical/high severity.

Rate-limited: max 2 concurrent investigations, 5-min per-equipment cooldown, and a
daily cap (ARVIS_DISPATCH_MAX_PER_DAY) — each one is a full multi-agent LLM run.
Same Queen.execute_swarm path as operator queries — identical verification.
"""

import time
import asyncio
import logging
from collections import deque
from typing import Dict, List, Optional

from agent_commercial.anomaly_watchdog import AnomalyEvent

logger = logging.getLogger("arvis.monitoring.dispatcher")


class InvestigationDispatcher:
    """
    Dispatches autonomous Queen swarm investigations for anomalies and alarms.

    Input:  AnomalyEvent (from watchdog) or Alarm object (direct callback)
    Output: advisory on SSE "monitor" channel + episodic memory archive
    """

    def __init__(
        self,
        queen=None,
        bms_state=None,
        sse_broadcaster=None,
        memory_orchestrator=None,
        event_bus=None,
        max_concurrent: int = 2,
        cooldown_per_equipment: int = 300,
        watchdog=None,
    ):
        self.queen = queen
        self.bms_state = bms_state
        self.sse = sse_broadcaster
        self.memory = memory_orchestrator
        self.event_bus = event_bus
        self.watchdog = watchdog                 # repeat evidence for drift confirmation
        self._max_concurrent = max_concurrent
        import os as _os
        self._max_per_day = int(_os.getenv("ARVIS_DISPATCH_MAX_PER_DAY", "48"))
        self._day = ""
        self._today = 0
        self._cooldown = cooldown_per_equipment
        self._active = 0
        self._last_investigation: Dict[str, float] = {}
        self._history: deque = deque(maxlen=200)
        self._stats = {
            "total_dispatched": 0,
            "suppressed_cooldown": 0,
            "suppressed_concurrency": 0,
            "completed": 0,
            "failed": 0,
            "watches_scheduled": 0,
        }

        # Agent-decided temporal watches (drift confirmation, post-maintenance verify).
        from agent_commercial.watch import WatchManager
        self.watch = WatchManager(bms_state=bms_state)
        self._watch_task = None

        # Subscribe to EventBus anomaly events
        if event_bus:
            try:
                event_bus.subscribe("anomaly_detected", self._on_anomaly_event)
                logger.info("[Dispatcher] Subscribed to EventBus 'anomaly_detected'")
            except Exception as e:
                logger.error(f"[Dispatcher] Failed to subscribe to EventBus: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    async def investigate_anomaly(self, anomaly: AnomalyEvent) -> Optional[Dict]:
        """Dispatch swarm investigation for a point-deviation anomaly.

        Severity gate: by default only "critical" anomalies (z≥4.0) trigger
        a full swarm investigation. "Significant" (3.0≤z<4.0) detections
        accumulate in the watchdog log but do not spawn Queen runs — they
        would flood the main log with autonomous investigation chatter and
        burn Bedrock tokens on low-confidence signals. Override via env
        ARVIS_DISPATCH_MIN_SEVERITY=significant if you want every detection
        investigated.
        """
        eq_id = anomaly.equipment_id

        import os as _os
        _min_sev = _os.getenv("ARVIS_DISPATCH_MIN_SEVERITY", "critical").lower()
        _sev_rank = {"low": 0, "medium": 1, "significant": 2, "high": 3, "critical": 4, "severe": 4}
        _anom_rank = _sev_rank.get(str(anomaly.severity).lower(), 2)
        _thresh_rank = _sev_rank.get(_min_sev, 4)
        if _anom_rank < _thresh_rank:
            self._stats.setdefault("suppressed_severity", 0)
            self._stats["suppressed_severity"] += 1
            # Don't just drop a sub-critical deviation — WATCH it. If it's sustained
            # (or worsens) over the window, it gets re-investigated; transients self-clear.
            try:
                await self.schedule_drift_confirmation(anomaly)
            except Exception as e:
                logger.debug(f"[Dispatcher] drift-watch schedule failed: {e}")
            return None

        ok, why = self._dispatch_check(eq_id)
        if not ok:
            if why in ("busy", "daily_cap"):
                # Not dropped: watch it, and investigate later if it is still happening.
                try:
                    await self.schedule_drift_confirmation(anomaly)
                except Exception as e:
                    logger.debug(f"[Dispatcher] deferral watch failed: {e}")
            return None

        self._count_dispatch(eq_id)
        self._active += 1

        try:
            query = self._build_anomaly_query(anomaly)
            context = await self._build_anomaly_context(anomaly)

            result = await self._run_swarm(query, context)
            if result:
                await self._publish_result("anomaly", anomaly.equipment_id, result,
                                           point_id=anomaly.point_id, severity=anomaly.severity,
                                           z_score=anomaly.z_score, deviation_pct=anomaly.deviation_pct)
                await self._archive(anomaly.equipment_id, result)
            return result

        except Exception as e:
            self._stats["failed"] += 1
            logger.error(f"[Dispatcher] Anomaly investigation failed for {eq_id}: {e}")
            return None
        finally:
            self._active -= 1
            self._stats["completed"] += 1

    async def investigate_alarm(self, alarm) -> Optional[Dict]:
        """Dispatch swarm investigation for a BMS alarm (bypasses watchdog)."""
        eq_id = getattr(alarm, "equipment_id", "unknown")

        if not self._dispatch_check(eq_id)[0]:
            return None

        self._count_dispatch(eq_id)
        self._active += 1

        try:
            query = self._build_alarm_query(alarm)
            context = await self._build_alarm_context(alarm)

            result = await self._run_swarm(query, context)
            if result:
                sev = getattr(alarm, "severity", None)
                await self._publish_result("alarm", eq_id, result, alarm_id=getattr(alarm, "alarm_id", ""),
                                           severity=getattr(sev, "value", str(sev)) if sev else None)
                await self._archive(eq_id, result)
            return result

        except Exception as e:
            self._stats["failed"] += 1
            logger.error(f"[Dispatcher] Alarm investigation failed for {eq_id}: {e}")
            return None
        finally:
            self._active -= 1
            self._stats["completed"] += 1

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "active_investigations": self._active,
            "tracked_equipment": len(self._last_investigation),
            "open_watches": len(self.watch.open_watches()),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT-DECIDED WATCHES (wake / sleep / re-investigate over time)
    # ─────────────────────────────────────────────────────────────────────────

    async def schedule_drift_confirmation(self, anomaly: AnomalyEvent,
                                          window_seconds: Optional[float] = None):
        """Watch a sub-critical deviation: re-investigate only if it's SUSTAINED over the
        window (or the value moves), instead of alarming on a transient."""
        import os as _os
        window = window_seconds or float(_os.getenv("ARVIS_DRIFT_WATCH_SECONDS", "1800"))
        self._stats["watches_scheduled"] += 1
        return await self.watch.schedule(
            anomaly.equipment_id, anomaly.point_id,
            reason=f"confirm sustained deviation on {anomaly.point_id} "
                   f"(z={anomaly.z_score}, {anomaly.deviation_pct}%)",
            est_seconds=window, kind="drift_confirm")

    async def schedule_post_maintenance_verification(self, equipment_id: str, point_id: str = "",
                                                     hours: float = 24.0):
        """After a work order closes, auto-recheck the equipment N hours later: did the fix
        hold? Surfaces a verification advisory rather than assuming the repair worked."""
        self._stats["watches_scheduled"] += 1
        return await self.watch.schedule(
            equipment_id, point_id,
            reason=f"verify fix held on {equipment_id} ~{hours:.0f}h after maintenance",
            est_seconds=hours * 3600.0, kind="post_maintenance")

    async def _watch_recheck(self, watch, changed: bool, due: bool):
        """A watch's window is up. Drift: confirmed only if the watchdog flagged the same
        point again and again during the window — then (and only then) a full
        investigation. Post-maintenance: re-investigate whether the fix held.
        Returns ("resolved", payload)."""
        import os as _os
        if watch.kind == "drift_confirm":
            repeats = self._repeats(watch)
            need = int(_os.getenv("ARVIS_DRIFT_MIN_REPEATS", "3"))
            if repeats < need:
                self._publish("drift_watch_outcome", {"status": "cleared", "equipment_id": watch.equipment_id,
                                                      "point_id": watch.point_id, "repeats": repeats,
                                                      "reason": watch.reason})
                return ("resolved", {"status": "cleared", "repeats": repeats})
            self._publish("drift_watch_outcome", {"status": "confirmed", "equipment_id": watch.equipment_id,
                                                  "point_id": watch.point_id, "repeats": repeats,
                                                  "reason": watch.reason})
            why = f"deviation repeated {repeats}x over the watch window"
        else:
            why = "observation window elapsed"
        if not self._dispatch_check(watch.equipment_id, cooldown=False)[0]:
            return ("resolved", {"status": "not_investigated", "why": "no capacity"})
        self._count_dispatch(watch.equipment_id)
        query = (
            f"AUTONOMOUS WATCH RE-CHECK ({watch.kind}): {watch.reason}. "
            f"Trigger: {why}. Re-assess {watch.equipment_id}/{watch.point_id} against current "
            f"telemetry — is the condition real and sustained, or resolved?")
        ctx = {"autonomous": True, "trigger": f"watch_{watch.kind}",
               "watch_equipment": watch.equipment_id, "watch_point": watch.point_id}
        ctx.update(await self._get_equipment_readings(watch.equipment_id))
        self._active += 1
        try:
            result = await self._run_swarm(query, ctx)
        finally:
            self._active -= 1
        if result:
            await self._archive(watch.equipment_id, result)
            await self._publish_result(f"watch_{watch.kind}", watch.equipment_id, result, point_id=watch.point_id)
        return ("resolved", {"status": "investigated", "woke_on": why,
                             "advice": (result or {}).get("advice", "")[:200]})

    def _repeats(self, watch) -> int:
        """How many times the watchdog flagged this point since the watch began."""
        if self.watchdog is None or not hasattr(self.watchdog, "get_recent_anomalies"):
            return 0
        minutes = max(1, int((time.time() - watch.created_at.timestamp()) / 60) + 1)
        return sum(1 for a in self.watchdog.get_recent_anomalies(minutes)
                   if a.point_id == watch.point_id and a.timestamp >= watch.created_at)

    def start_watch_loop(self):
        """Start the background watch service (call from inside the running loop)."""
        if self._watch_task is not None and not self._watch_task.done():
            return
        try:
            self._watch_task = asyncio.ensure_future(
                self.watch.run(self._watch_recheck))
            logger.info("[Dispatcher] watch loop started")
        except RuntimeError:
            logger.debug("[Dispatcher] no event loop for watch loop")

    def stop_watch_loop(self):
        self.watch.stop()
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None

    def get_history(self, limit: int = 20) -> List[Dict]:
        items = list(self._history)[-limit:]
        return list(reversed(items))

    # ─────────────────────────────────────────────────────────────────────────
    # EVENT BUS CALLBACK
    # ─────────────────────────────────────────────────────────────────────────

    def _on_anomaly_event(self, event: dict) -> None:
        """EventBus callback — synchronous, schedules async investigation."""
        anomaly = event.get("payload")
        if not isinstance(anomaly, AnomalyEvent):
            return
        # Schedule in the running event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.investigate_anomaly(anomaly))
            else:
                loop.run_until_complete(self.investigate_anomaly(anomaly))
        except RuntimeError:
            # No event loop — skip (happens in sync test contexts)
            logger.debug("[Dispatcher] No event loop for anomaly dispatch")

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _dispatch_check(self, eq_id: str, cooldown: bool = True):
        """(ok, reason). Reasons: cooldown | busy | daily_cap | no_queen."""
        now = time.time()
        if cooldown and (now - self._last_investigation.get(eq_id, 0)) < self._cooldown:
            self._stats["suppressed_cooldown"] += 1
            logger.debug(f"[Dispatcher] Cooldown active for {eq_id}, skipping")
            return False, "cooldown"
        if self._active >= self._max_concurrent:
            self._stats["suppressed_concurrency"] += 1
            logger.debug(f"[Dispatcher] Max concurrent ({self._max_concurrent}) reached, deferring")
            return False, "busy"
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._today = today, 0
        if self._today >= self._max_per_day:
            self._stats.setdefault("suppressed_daily_cap", 0)
            self._stats["suppressed_daily_cap"] += 1
            logger.warning(f"[Dispatcher] daily investigation cap ({self._max_per_day}) reached")
            return False, "daily_cap"
        if not self.queen:
            logger.warning("[Dispatcher] Queen not available, skipping investigation")
            return False, "no_queen"
        return True, ""

    def _should_dispatch(self, eq_id: str) -> bool:
        return self._dispatch_check(eq_id)[0]

    def _count_dispatch(self, eq_id: str) -> None:
        self._stats["total_dispatched"] += 1
        self._last_investigation[eq_id] = time.time()
        self._today += 1

    def _build_anomaly_query(self, anomaly: AnomalyEvent) -> str:
        return (
            f"AUTONOMOUS INVESTIGATION: Anomaly detected on equipment {anomaly.equipment_id}. "
            f"Point '{anomaly.point_id}' ({anomaly.point_name}) reading {anomaly.current_value} {anomaly.unit} "
            f"when expected ~{anomaly.expected_value} {anomaly.unit} "
            f"(deviation {anomaly.deviation_pct}%, z-score {anomaly.z_score}). "
            f"Determine: is this a real equipment fault, sensor malfunction, or operational change? "
            f"If real fault — assess impact, cascade risk, and recommend action."
        )

    def _build_alarm_query(self, alarm) -> str:
        severity = getattr(alarm, "severity", None)
        severity_str = getattr(severity, "value", str(severity)) if severity else "unknown"
        desc = getattr(alarm, "description", "No description")
        eq_id = getattr(alarm, "equipment_id", "unknown")
        return (
            f"AUTONOMOUS INVESTIGATION: {severity_str.upper()} alarm on {eq_id}. "
            f"Description: {desc}. "
            f"Diagnose root cause, assess cascade risk to related systems, "
            f"and recommend immediate action."
        )

    async def _build_anomaly_context(self, anomaly: AnomalyEvent) -> Dict:
        context = {
            "autonomous": True,
            "trigger": "anomaly_deviation",
            "anomaly_point": anomaly.point_id,
            "anomaly_equipment": anomaly.equipment_id,
            "deviation_pct": anomaly.deviation_pct,
            "z_score": anomaly.z_score,
            "severity": anomaly.severity,
        }
        context.update(await self._get_equipment_readings(anomaly.equipment_id))
        return context

    async def _build_alarm_context(self, alarm) -> Dict:
        eq_id = getattr(alarm, "equipment_id", "unknown")
        severity = getattr(alarm, "severity", None)
        context = {
            "autonomous": True,
            "trigger": "alarm",
            "alarm_id": getattr(alarm, "alarm_id", ""),
            "alarm_equipment": eq_id,
            "severity": getattr(severity, "value", str(severity)) if severity else "unknown",
        }
        context.update(await self._get_equipment_readings(eq_id))
        return context

    async def _get_equipment_readings(self, eq_id: str) -> Dict:
        if not self.bms_state or not eq_id or eq_id == "unknown":
            return {}
        try:
            points = await self.bms_state.get_points_by_equipment(eq_id)
            readings = {p.point_id: p.value for p in points if p.value is not None}
            return {"equipment_readings": readings} if readings else {}
        except Exception as e:
            logger.debug(f"[Dispatcher] Failed to get readings for {eq_id}: {e}")
            return {}

    async def _run_swarm(self, query: str, context: Dict) -> Optional[Dict]:
        """Execute Queen swarm — same path as operator queries."""
        try:
            logger.info(f"[Dispatcher] Launching swarm: {query[:80]}...")
            result = await self.queen.execute_swarm(
                query=query,
                context={**context, "autonomous": True},
                channel="monitor",
            )
            return result
        except Exception as e:
            logger.error(f"[Dispatcher] Swarm execution failed: {e}")
            return None

    def _publish(self, event_type: str, payload: Dict) -> None:
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish({"type": event_type, "payload": payload})
        except Exception as e:
            logger.error(f"[Dispatcher] publish {event_type} failed: {e}")

    async def _publish_result(self, trigger: str, equipment_id: str, result: Dict, **extra) -> None:
        """The conclusion of an autonomous investigation, to whoever needs it: the event
        bus (WhatsApp engineer) and the dashboard's monitor stream. (The SSE call used to
        pass payload= to a method that takes data=, and the broadcaster was never set,
        so these conclusions reached nobody.)"""
        ctx = result.get("context") or {}
        payload = {
            "trigger": trigger, "equipment_id": equipment_id,
            "advice": result.get("advice", ""),
            "confidence": result.get("confidence"), "abstained": bool(result.get("abstained")),
            "plan_id": getattr(result.get("plan"), "id", None),
            "terminal_advisories": ctx.get("_terminal_advisories_fired") or [],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **{k: v for k, v in extra.items() if v is not None},
        }
        self._publish("investigation_concluded", payload)
        if self.sse:
            try:
                await self.sse.broadcast("autonomous_advisory", payload, channel="monitor")
            except Exception as e:
                logger.error(f"[Dispatcher] SSE broadcast failed: {e}")

    async def _archive(self, equipment_id: str, result: Dict) -> None:
        """Archive investigation result to episodic memory."""
        self._history.append({
            "timestamp": time.time(),
            "equipment_id": equipment_id,
            "summary": result.get("advice", "")[:200],
        })
        if self.memory and hasattr(self.memory, "archive_investigation"):
            try:
                await self.memory.archive_investigation(result)
            except Exception as e:
                logger.debug(f"[Dispatcher] Memory archive failed: {e}")
