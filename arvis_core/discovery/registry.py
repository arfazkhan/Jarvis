"""Runtime-mutable poll registry for ARVIS Discovery.

Bridges the abstract notion of "ARVIS poll scope" to the concrete BACnet
adapter. New points enter PROBATION for 24h (values are read but excluded
from alarming) before being promoted to ACTIVE.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from arvis_core.discovery.security import sign_action

logger = logging.getLogger("arvis.discovery.registry")


class PointState(Enum):
    PROBATION = "probation"      # newly registered, alarms suppressed
    ACTIVE = "active"
    QUARANTINED = "quarantined"  # anomalous, auto-removed from poll
    REMOVED = "removed"


@dataclass
class RegisteredPoint:
    point_id: str
    equipment_id: str
    cadence_seconds: float
    priority: str  # "critical" | "nice_to_have" | "cosmetic"
    state: PointState = PointState.PROBATION
    registered_at: float = field(default_factory=time.time)
    probation_ends_at: float = field(default_factory=lambda: time.time() + 86400)
    registered_by: str = "discovery_agent"
    signature: str = ""
    initial_value: Optional[float] = None
    anomaly_count: int = 0


class ARVISPollRegistry:
    """Runtime-mutable poll registry. Bridges to BACnetSimulatorAdapter."""

    _lock = threading.RLock()

    def __init__(self, adapter, audit_log) -> None:
        self._adapter = adapter
        self._audit = audit_log
        self._registered: Dict[str, RegisteredPoint] = {}
        self._on_change_callbacks: List[Callable] = []

    def register(self, point: RegisteredPoint) -> Tuple[bool, str]:
        with self._lock:
            if point.point_id in self._registered:
                return False, "already registered (idempotent)"

            payload = {
                "point_id": point.point_id,
                "cadence": point.cadence_seconds,
                "priority": point.priority,
                "registered_at": point.registered_at,
            }
            point.signature = sign_action(payload, point.point_id)

            self._registered[point.point_id] = point

            # Push to adapter's dynamic-poll registry. Sim adapter records into
            # a dict; production adapter wires into the real poller.
            if hasattr(self._adapter, "register_dynamic_point"):
                try:
                    self._adapter.register_dynamic_point(
                        point.point_id, point.cadence_seconds
                    )
                except Exception as e:
                    logger.warning(
                        "[PollRegistry] adapter.register_dynamic_point failed: %s", e
                    )

            self._audit.append(
                agent_id=point.registered_by,
                action_type="register",
                payload={
                    "cadence": point.cadence_seconds,
                    "priority": point.priority,
                    "probation_ends": point.probation_ends_at,
                },
                point_id=point.point_id,
                equipment_id=point.equipment_id,
                outcome="success",
            )

            for cb in self._on_change_callbacks:
                try:
                    cb("register", point)
                except Exception:
                    pass

            return True, "registered"

    def quarantine(self, point_id: str, reason: str) -> bool:
        with self._lock:
            p = self._registered.get(point_id)
            if not p:
                return False
            p.state = PointState.QUARANTINED
            self._audit.append(
                agent_id="discovery_agent",
                action_type="quarantine",
                payload={"reason": reason},
                point_id=point_id,
                equipment_id=p.equipment_id,
                outcome="quarantined",
            )
            return True

    def promote_to_active(self, point_id: str) -> bool:
        """Called when probation expires + no anomalies."""
        with self._lock:
            p = self._registered.get(point_id)
            if not p:
                return False
            if time.time() < p.probation_ends_at:
                return False
            if p.state != PointState.PROBATION:
                return False
            p.state = PointState.ACTIVE
            self._audit.append(
                agent_id="discovery_agent",
                action_type="promote_to_active",
                payload={"probation_duration_s": time.time() - p.registered_at},
                point_id=point_id,
                equipment_id=p.equipment_id,
                outcome="active",
            )
            return True

    def list_probation(self) -> List[RegisteredPoint]:
        with self._lock:
            return [p for p in self._registered.values() if p.state == PointState.PROBATION]

    def is_registered(self, point_id: str) -> bool:
        return point_id in self._registered

    def get(self, point_id: str) -> Optional[RegisteredPoint]:
        return self._registered.get(point_id)

    def all_registered(self) -> List[RegisteredPoint]:
        return list(self._registered.values())

    def on_change(self, cb: Callable) -> None:
        self._on_change_callbacks.append(cb)
