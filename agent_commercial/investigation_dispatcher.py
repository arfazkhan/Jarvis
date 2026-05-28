"""
Investigation Dispatcher
========================

Converts anomaly events (from AnomalyWatchdog) and alarm callbacks into
autonomous Queen swarm investigations. Broadcasts results to SSE "monitor"
channel. Archives to episodic memory.

Subscribes to EventBus "anomaly_detected" events.
Also accepts direct alarm callbacks for critical/high severity.

Rate-limited: max 2 concurrent investigations, 5-min per-equipment cooldown.
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
    ):
        self.queen = queen
        self.bms_state = bms_state
        self.sse = sse_broadcaster
        self.memory = memory_orchestrator
        self.event_bus = event_bus
        self._max_concurrent = max_concurrent
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
        }

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
            return None

        if not self._should_dispatch(eq_id):
            return None

        self._stats["total_dispatched"] += 1
        self._last_investigation[eq_id] = time.time()
        self._active += 1

        try:
            query = self._build_anomaly_query(anomaly)
            context = await self._build_anomaly_context(anomaly)

            result = await self._run_swarm(query, context)
            if result:
                await self._broadcast_anomaly_result(anomaly, result)
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

        if not self._should_dispatch(eq_id):
            return None

        self._stats["total_dispatched"] += 1
        self._last_investigation[eq_id] = time.time()
        self._active += 1

        try:
            query = self._build_alarm_query(alarm)
            context = await self._build_alarm_context(alarm)

            result = await self._run_swarm(query, context)
            if result:
                await self._broadcast_alarm_result(alarm, result)
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
        }

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

    def _should_dispatch(self, eq_id: str) -> bool:
        now = time.time()
        last = self._last_investigation.get(eq_id, 0)
        if (now - last) < self._cooldown:
            self._stats["suppressed_cooldown"] += 1
            logger.debug(f"[Dispatcher] Cooldown active for {eq_id}, skipping")
            return False
        if self._active >= self._max_concurrent:
            self._stats["suppressed_concurrency"] += 1
            logger.debug(f"[Dispatcher] Max concurrent ({self._max_concurrent}) reached, skipping")
            return False
        if not self.queen:
            logger.warning("[Dispatcher] Queen not available, skipping investigation")
            return False
        return True

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

    async def _broadcast_anomaly_result(self, anomaly: AnomalyEvent, result: Dict) -> None:
        if not self.sse:
            return
        try:
            await self.sse.broadcast(
                event_type="autonomous_advisory",
                payload={
                    "trigger": "anomaly",
                    "point_id": anomaly.point_id,
                    "equipment_id": anomaly.equipment_id,
                    "deviation_pct": anomaly.deviation_pct,
                    "z_score": anomaly.z_score,
                    "severity": anomaly.severity,
                    "advisory": result.get("advice", ""),
                    "timestamp": anomaly.timestamp.isoformat(),
                },
                channel="monitor",
            )
        except Exception as e:
            logger.error(f"[Dispatcher] SSE broadcast failed: {e}")

    async def _broadcast_alarm_result(self, alarm, result: Dict) -> None:
        if not self.sse:
            return
        try:
            await self.sse.broadcast(
                event_type="autonomous_advisory",
                payload={
                    "trigger": "alarm",
                    "alarm_id": getattr(alarm, "alarm_id", ""),
                    "equipment_id": getattr(alarm, "equipment_id", ""),
                    "advisory": result.get("advice", ""),
                    "timestamp": str(getattr(alarm, "timestamp", "")),
                },
                channel="monitor",
            )
        except Exception as e:
            logger.error(f"[Dispatcher] SSE broadcast (alarm) failed: {e}")

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
