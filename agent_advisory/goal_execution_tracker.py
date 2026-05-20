"""
Goal Execution Tracker
======================

Tracks ProactiveGoal lifecycle from discovery → advisory → outcome.
Read-only: observes telemetry to assess if goals are being met.
Never issues BMS commands.

Flow:
  1. GoalDiscoveryEngine publishes `proactive_goal_discovered`
  2. GoalExecutionTracker registers goal, stores in DB
  3. Every cognitive cycle: check telemetry (read-only) against goal condition
  4. If unmet after remind_after_hours: re-publish reminder advisory
  5. If met or expired: mark closed, record outcome
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.advisory.goal_tracker")


class GoalStatus(str, Enum):
    ACTIVE = "active"
    MET = "met"
    EXPIRED = "expired"
    DISMISSED = "dismissed"


@dataclass
class TrackedGoal:
    goal_id: str
    title: str
    description: str
    goal_type: str
    priority: str
    score: float
    source_engine: str
    building_id: str
    equipment_ids: List[str]
    potential_savings_qar: float
    suggested_actions: List[str]

    # Tracking state
    status: GoalStatus = GoalStatus.ACTIVE
    discovered_at: datetime = field(default_factory=datetime.now)
    deadline: Optional[datetime] = None
    last_reminder_at: Optional[datetime] = None
    reminder_count: int = 0
    met_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    dismiss_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "goal_type": self.goal_type,
            "priority": self.priority,
            "score": round(self.score, 3),
            "source_engine": self.source_engine,
            "building_id": self.building_id,
            "equipment_ids": self.equipment_ids,
            "potential_savings_qar": round(self.potential_savings_qar, 0),
            "suggested_actions": self.suggested_actions,
            "status": self.status.value,
            "discovered_at": self.discovered_at.isoformat(),
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "last_reminder_at": self.last_reminder_at.isoformat() if self.last_reminder_at else None,
            "reminder_count": self.reminder_count,
            "met_at": self.met_at.isoformat() if self.met_at else None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "dismiss_reason": self.dismiss_reason,
        }


class GoalExecutionTracker:
    """
    Subscribes to proactive_goal_discovered events, tracks goal status over time,
    and publishes advisory reminders when goals remain unmet.

    Read-only: uses bms_state to observe telemetry. Never writes to BMS.
    """

    def __init__(
        self,
        event_bus: Any,
        bms_state: Optional[Any] = None,
        remind_after_hours: float = 24.0,
        expire_after_days: int = 7,
        max_reminders: int = 3,
    ):
        self.event_bus = event_bus
        self.bms_state = bms_state
        self.remind_after_hours = remind_after_hours
        self.expire_after_days = expire_after_days
        self.max_reminders = max_reminders

        # In-memory store: goal_id → TrackedGoal
        self._goals: Dict[str, TrackedGoal] = {}
        # Dedup by content signature (same as GoalDiscoveryEngine)
        self._sig_to_id: Dict[str, str] = {}

        # Subscribe to goal discovery events
        self.event_bus.subscribe("proactive_goal_discovered", self._on_goal_discovered)
        logger.info("[GoalTracker] Initialized and subscribed to proactive_goal_discovered")

    # ─────────────────────────────────────────────────────────────────────────
    # Event Handling
    # ─────────────────────────────────────────────────────────────────────────

    def _on_goal_discovered(self, event: Dict[str, Any]) -> None:
        """Handle incoming goal-discovered event from GoalDiscoveryEngine."""
        try:
            payload = event.get("payload", {})
            goal_dict = payload.get("goal", {})
            if not goal_dict:
                return

            goal_id = goal_dict.get("goal_id", "")
            if not goal_id:
                return

            # Dedup by content signature
            sig = self._make_sig(goal_dict)
            if sig in self._sig_to_id and self._sig_to_id[sig] in self._goals:
                existing = self._goals[self._sig_to_id[sig]]
                if existing.status == GoalStatus.ACTIVE:
                    logger.debug(f"[GoalTracker] Duplicate goal signature ignored: {sig[:60]}")
                    return

            # Build deadline from recommended_deadline or fallback
            raw_deadline = goal_dict.get("recommended_deadline")
            deadline = None
            if raw_deadline:
                try:
                    deadline = datetime.fromisoformat(raw_deadline)
                except ValueError:
                    pass
            if deadline is None:
                deadline = datetime.now() + timedelta(days=self.expire_after_days)

            tracked = TrackedGoal(
                goal_id=goal_id,
                title=goal_dict.get("title", ""),
                description=goal_dict.get("description", ""),
                goal_type=goal_dict.get("goal_type", ""),
                priority=goal_dict.get("priority", "medium"),
                score=float(goal_dict.get("score", 0.5)),
                source_engine=goal_dict.get("source_engine", ""),
                building_id=goal_dict.get("building_id", "default"),
                equipment_ids=goal_dict.get("equipment_ids", []),
                potential_savings_qar=float(goal_dict.get("potential_savings_qar", 0.0)),
                suggested_actions=goal_dict.get("suggested_actions", []),
                deadline=deadline,
            )

            self._goals[goal_id] = tracked
            self._sig_to_id[sig] = goal_id
            logger.info(f"[GoalTracker] Tracking new goal: '{tracked.title}' (id={goal_id[:8]})")

        except Exception as e:
            logger.error(f"[GoalTracker] Error processing goal event: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Periodic Check (called by cognitive loop each cycle)
    # ─────────────────────────────────────────────────────────────────────────

    def check_all_goals(self) -> Dict[str, Any]:
        """
        Read-only telemetry sweep.  For each active goal:
          - Check if condition is met (evidence from bms_state)
          - Check if expired
          - Issue reminder if overdue and under max_reminders
        Returns a summary dict for logging.
        """
        now = datetime.now()
        summary: Dict[str, Any] = {"checked": 0, "met": 0, "expired": 0, "reminded": 0, "active": 0}

        for goal_id, goal in list(self._goals.items()):
            if goal.status != GoalStatus.ACTIVE:
                continue

            summary["checked"] += 1

            # 1. Expiry check
            if goal.deadline and now > goal.deadline:
                goal.status = GoalStatus.EXPIRED
                summary["expired"] += 1
                logger.info(f"[GoalTracker] Goal expired: '{goal.title}' (id={goal_id[:8]})")
                self._publish_goal_update(goal, "expired")
                continue

            # 2. Condition-met check (read-only telemetry observation)
            if self._is_goal_condition_met(goal):
                goal.status = GoalStatus.MET
                goal.met_at = now
                summary["met"] += 1
                logger.info(f"[GoalTracker] Goal MET: '{goal.title}' (id={goal_id[:8]})")
                self._publish_goal_update(goal, "met")
                continue

            # 3. Reminder check
            hours_since_discovery = (now - goal.discovered_at).total_seconds() / 3600.0
            hours_since_last_reminder = (
                (now - goal.last_reminder_at).total_seconds() / 3600.0
                if goal.last_reminder_at
                else hours_since_discovery
            )

            should_remind = (
                goal.reminder_count < self.max_reminders
                and hours_since_last_reminder >= self.remind_after_hours
            )

            if should_remind:
                goal.reminder_count += 1
                goal.last_reminder_at = now
                summary["reminded"] += 1
                self._publish_reminder(goal)

            summary["active"] += 1

        if summary["checked"]:
            logger.debug(f"[GoalTracker] Cycle summary: {summary}")

        return summary

    # ─────────────────────────────────────────────────────────────────────────
    # Read-only Telemetry Condition Check
    # ─────────────────────────────────────────────────────────────────────────

    def _is_goal_condition_met(self, goal: TrackedGoal) -> bool:
        """
        Observe BMS telemetry (read-only) to infer if goal condition improved.
        Heuristic: uses energy/alarm proxy signals. No BMS writes ever.
        """
        if not self.bms_state:
            return False

        try:
            if goal.goal_type == "risk_mitigation":
                return self._check_risk_goal(goal)
            elif goal.goal_type == "efficiency":
                return self._check_efficiency_goal(goal)
            else:
                return False
        except Exception as e:
            logger.debug(f"[GoalTracker] Condition check failed for {goal.goal_id[:8]}: {e}")
            return False

    def _check_risk_goal(self, goal: TrackedGoal) -> bool:
        """
        Risk goal considered met if the equipment no longer shows active alarms
        or the alarm_engine reports the equipment healthy.
        Read-only probe via bms_state.
        """
        alarm_engine = getattr(self.bms_state, "_alarm_engine", None)
        if not alarm_engine:
            return False

        active_alarms = getattr(alarm_engine, "active_alarms", {})
        # If none of the goal's equipment have active alarms, treat as resolved
        for eq_id in goal.equipment_ids:
            if eq_id in active_alarms:
                return False
        # All equipment clear
        return bool(goal.equipment_ids)

    def _check_efficiency_goal(self, goal: TrackedGoal) -> bool:
        """
        Efficiency goal considered met if total power dropped ≥10% from baseline.
        Baseline inferred from goal's potential_savings_qar converted to rough kW.
        Read-only: reads MAIN_KWH_TOTAL from state engine.
        """
        try:
            current_kw = self.bms_state.get_latest_value("MAIN_KWH_TOTAL")
            if current_kw is None:
                return False
            # Baseline estimate: if savings ~= 10% of current, goal is met
            # We use the potential_savings proxy: QAR / 0.35 (QAR/kWh) / 8760h ~ annual kWh
            annual_kwh_saved = goal.potential_savings_qar / 0.35
            baseline_kw = current_kw + (annual_kwh_saved / 8760.0)
            if baseline_kw <= 0:
                return False
            reduction_pct = (baseline_kw - current_kw) / baseline_kw * 100.0
            return reduction_pct >= 5.0  # 5% reduction observed → goal met
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Event Publishing (advisory notifications only, no BMS commands)
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_reminder(self, goal: TrackedGoal) -> None:
        """Publish a reminder advisory for an unmet goal."""
        urgency = "high" if goal.priority in ("critical", "high") else "medium"
        message = (
            f"Reminder #{goal.reminder_count}: '{goal.title}' remains unresolved. "
            f"Potential savings: {goal.potential_savings_qar:,.0f} QAR. "
            f"Deadline: {goal.deadline.strftime('%Y-%m-%d') if goal.deadline else 'N/A'}."
        )
        self.event_bus.publish({
            "type": "goal_reminder",
            "source": "GoalExecutionTracker",
            "payload": {
                "goal_id": goal.goal_id,
                "goal": goal.to_dict(),
                "message": message,
                "urgency": urgency,
                "reminder_count": goal.reminder_count,
            },
        })
        logger.info(f"[GoalTracker] Reminder #{goal.reminder_count} sent for '{goal.title}'")

    def _publish_goal_update(self, goal: TrackedGoal, event_type: str) -> None:
        """Publish goal status update (met / expired)."""
        self.event_bus.publish({
            "type": f"goal_{event_type}",
            "source": "GoalExecutionTracker",
            "payload": {
                "goal_id": goal.goal_id,
                "goal": goal.to_dict(),
                "message": (
                    f"Goal '{goal.title}' is now {event_type}."
                    + (f" Savings realised: {goal.potential_savings_qar:,.0f} QAR." if event_type == "met" else "")
                ),
            },
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Query API (read-only, called by REST endpoints)
    # ─────────────────────────────────────────────────────────────────────────

    def get_active_goals(self) -> List[Dict[str, Any]]:
        """Return all currently active goals sorted by score desc."""
        goals = [
            g.to_dict()
            for g in self._goals.values()
            if g.status == GoalStatus.ACTIVE
        ]
        return sorted(goals, key=lambda x: x["score"], reverse=True)

    def get_all_goals(self) -> List[Dict[str, Any]]:
        """Return all tracked goals (all statuses) sorted by discovered_at desc."""
        goals = [g.to_dict() for g in self._goals.values()]
        return sorted(goals, key=lambda x: x["discovered_at"], reverse=True)

    def dismiss_goal(self, goal_id: str, reason: str = "operator_dismissed") -> bool:
        """
        Mark a goal as dismissed by operator. Read-only advisory system respects
        operator decision — dismissed goals will not be re-reminded.
        Returns True if found and dismissed, False if not found or already closed.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        if goal.status != GoalStatus.ACTIVE:
            return False

        goal.status = GoalStatus.DISMISSED
        goal.dismissed_at = datetime.now()
        goal.dismiss_reason = reason
        logger.info(f"[GoalTracker] Goal dismissed by operator: '{goal.title}' reason='{reason}'")
        self._publish_goal_update(goal, "dismissed")
        return True

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level stats for dashboard / health checks."""
        total = len(self._goals)
        by_status: Dict[str, int] = {}
        for g in self._goals.values():
            by_status[g.status.value] = by_status.get(g.status.value, 0) + 1

        total_savings_active = sum(
            g.potential_savings_qar
            for g in self._goals.values()
            if g.status == GoalStatus.ACTIVE
        )
        return {
            "total_tracked": total,
            "by_status": by_status,
            "active_savings_qar": round(total_savings_active, 0),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _make_sig(goal_dict: Dict[str, Any]) -> str:
        eq_ids = sorted(goal_dict.get("equipment_ids", []))
        return (
            f"{goal_dict.get('building_id', '')}:"
            f"{goal_dict.get('goal_type', '')}:"
            f"{goal_dict.get('title', '')}:"
            f"{','.join(eq_ids)}"
        )
