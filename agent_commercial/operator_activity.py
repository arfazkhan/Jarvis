"""
Operator Activity Feed — tracks recent operator actions for concurrent awareness.

Provides ARVIS with context about what operators have recently done (setpoint changes,
alarm acknowledgments, overrides) so the swarm can correlate building state changes
to human actions rather than diagnosing phantom faults.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.operator_activity")


@dataclass
class OperatorAction:
    operator_id: str
    action_type: str  # setpoint_change, alarm_ack, query, override, maintenance
    target: str  # equipment_id or point_id
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class OperatorActivityFeed:
    """Ring buffer of recent operator actions for grounding context injection."""

    def __init__(self, window_minutes: int = 30, max_actions: int = 500):
        self._actions: deque = deque(maxlen=max_actions)
        self._window_minutes = window_minutes

    def record(self, action: OperatorAction) -> None:
        self._actions.append(action)
        logger.debug(
            f"[ActivityFeed] {action.operator_id}: {action.action_type} on {action.target}"
        )

    def record_setpoint_change(
        self,
        operator_id: str,
        point_id: str,
        old_value: Optional[float],
        new_value: float,
        reason: str = "",
    ) -> None:
        self.record(OperatorAction(
            operator_id=operator_id,
            action_type="setpoint_change",
            target=point_id,
            details={
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason,
            },
        ))

    def record_alarm_ack(self, operator_id: str, alarm_id: str) -> None:
        self.record(OperatorAction(
            operator_id=operator_id,
            action_type="alarm_ack",
            target=alarm_id,
        ))

    def record_override(
        self, operator_id: str, equipment_id: str, details: Dict[str, Any]
    ) -> None:
        self.record(OperatorAction(
            operator_id=operator_id,
            action_type="override",
            target=equipment_id,
            details=details,
        ))

    def recent(self, minutes: Optional[int] = None) -> List[OperatorAction]:
        cutoff = datetime.now() - timedelta(minutes=minutes or self._window_minutes)
        return [a for a in self._actions if a.timestamp > cutoff]

    def to_grounding_context(self, minutes: int = 5) -> str:
        """Format recent actions as a grounding block for swarm context injection."""
        recent = self.recent(minutes=minutes)
        if not recent:
            return ""
        lines = [f"RECENT OPERATOR ACTIONS (last {minutes} min):"]
        for a in recent:
            detail_str = ""
            if a.action_type == "setpoint_change":
                old = a.details.get("old_value")
                new = a.details.get("new_value")
                detail_str = f" ({old}→{new})"
                if a.details.get("reason"):
                    detail_str += f" reason: {a.details['reason']}"
            elif a.details:
                detail_str = f" {a.details}"
            lines.append(
                f"  [{a.timestamp:%H:%M:%S}] {a.operator_id}: "
                f"{a.action_type} on {a.target}{detail_str}"
            )
        return "\n".join(lines)

    def actions_affecting(self, target: str, minutes: int = 10) -> List[OperatorAction]:
        """Get actions affecting a specific equipment/point in the last N minutes."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [
            a for a in self._actions
            if a.timestamp > cutoff and (a.target == target or target in a.target)
        ]

    def clear(self) -> None:
        self._actions.clear()
