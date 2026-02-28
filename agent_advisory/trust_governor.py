"""
Trust Governor
==============

Transforms trust metrics from a passive observation into an active
behavioral governor.  When operators follow ARVIS less (low trust),
ARVIS adapts:

  - Caps confidence on recommendations (prevents overconfidence)
  - Increases evidence density (more proof, less narrative)
  - Tightens escalation sensitivity (surfaces issues sooner)
  - Throttles proactive suggestions (reduces "crying wolf")

CRITICAL RULE: Terminal and Institutional severity goals are NEVER
throttled or dampened, regardless of trust level.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Any, Dict

logger = logging.getLogger("arvis.advisory.trust_governor")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class TrustLevel(Enum):
    """Discretized trust bands."""
    HIGH = "high"           # > 0.8 — operator follows most advice
    NOMINAL = "nominal"     # 0.6 - 0.8 — normal operating trust
    CAUTION = "caution"     # 0.4 - 0.6 — significant distrust
    LOW = "low"             # < 0.4 — operator rarely follows advice


class VerbosityLevel(Enum):
    """How much explanation ARVIS provides."""
    CONCISE = "concise"     # Minimal — operator knows the domain
    NORMAL = "normal"       # Standard explanations
    DETAILED = "detailed"   # Extra proof — operator needs convincing


# Severity levels that bypass trust throttling entirely
IMMUNE_SEVERITIES = {"terminal", "institutional", "critical_safety"}


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BehavioralModifiers:
    """
    Output of the Trust Governor — modifies ARVIS's behavior based
    on current trust level.
    """
    trust_level: TrustLevel
    trust_score: float

    # Recommendation adjustments
    confidence_ceiling: float        # Max confidence ARVIS will state
    verbosity: VerbosityLevel        # How much explanation to include
    evidence_depth: int              # Number of cited signals (more = more proof)

    # Escalation adjustments
    escalation_sensitivity: float    # 0.0-1.0, lower = escalate sooner

    # Proactive behavior
    proactive_throttle: float        # 0.0-1.0, fraction of suggestions suppressed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trust_level": self.trust_level.value,
            "trust_score": round(self.trust_score, 3),
            "confidence_ceiling": self.confidence_ceiling,
            "verbosity": self.verbosity.value,
            "evidence_depth": self.evidence_depth,
            "escalation_sensitivity": self.escalation_sensitivity,
            "proactive_throttle": self.proactive_throttle,
        }


# ═══════════════════════════════════════════════════════════════════════════
# TRUST GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════

class TrustGovernor:
    """
    Behavioral governor that adapts ARVIS's tone, confidence, and
    proactive frequency based on operator trust levels.

    Trust is measured by the RecommendationTracker's adoption rate
    and accuracy metrics.

    INVARIANT: Terminal and Institutional alerts are NEVER throttled.
    """

    # ── Trust Level → Behavioral Profile Mapping ──
    PROFILES = {
        TrustLevel.HIGH: {
            "confidence_ceiling": 0.95,
            "verbosity": VerbosityLevel.CONCISE,
            "evidence_depth": 2,
            "escalation_sensitivity": 0.50,   # Normal — don't nag
            "proactive_throttle": 0.0,        # No throttling
        },
        TrustLevel.NOMINAL: {
            "confidence_ceiling": 0.80,
            "verbosity": VerbosityLevel.NORMAL,
            "evidence_depth": 3,
            "escalation_sensitivity": 0.50,
            "proactive_throttle": 0.0,
        },
        TrustLevel.CAUTION: {
            "confidence_ceiling": 0.65,
            "verbosity": VerbosityLevel.DETAILED,
            "evidence_depth": 5,              # More cross-sensor proof
            "escalation_sensitivity": 0.35,   # Tighter — surface issues sooner
            "proactive_throttle": 0.25,       # Suppress 25% of suggestions
        },
        TrustLevel.LOW: {
            "confidence_ceiling": 0.50,
            "verbosity": VerbosityLevel.DETAILED,
            "evidence_depth": 7,              # Maximum evidence density
            "escalation_sensitivity": 0.20,   # Aggressive — nag early
            "proactive_throttle": 0.50,       # Suppress 50% of suggestions
        },
    }

    def __init__(self, recommendation_tracker: Optional[Any] = None):
        self.tracker = recommendation_tracker
        self._last_trust_score: float = 0.85  # Default: nominal
        self._last_modifiers: Optional[BehavioralModifiers] = None
        logger.info("[TRUST_GOV] Trust Governor initialized")

    def _get_trust_score(self, building_id: str = "default") -> float:
        """Get the current trust score from the recommendation tracker."""
        if not self.tracker:
            return self._last_trust_score

        try:
            metrics = self.tracker.calculate_trust_metrics(
                window_days=30,
                building_id=building_id
            )
            if metrics.get("status") == "insufficient_data":
                return self._last_trust_score

            score = metrics.get("overall_trust_score", self._last_trust_score)
            self._last_trust_score = score
            return score
        except Exception as e:
            logger.debug(f"[TRUST_GOV] Could not calculate trust: {e}")
            return self._last_trust_score

    def _classify_trust(self, score: float) -> TrustLevel:
        """Classify a trust score into a discrete level."""
        if score > 0.8:
            return TrustLevel.HIGH
        elif score > 0.6:
            return TrustLevel.NOMINAL
        elif score > 0.4:
            return TrustLevel.CAUTION
        else:
            return TrustLevel.LOW

    def get_modifiers(self, building_id: str = "default") -> BehavioralModifiers:
        """
        Calculate behavioral modifiers based on current trust level.

        Returns:
            BehavioralModifiers with confidence ceiling, verbosity,
            evidence depth, escalation sensitivity, and throttle rate.
        """
        score = self._get_trust_score(building_id)
        level = self._classify_trust(score)
        profile = self.PROFILES[level]

        modifiers = BehavioralModifiers(
            trust_level=level,
            trust_score=score,
            confidence_ceiling=profile["confidence_ceiling"],
            verbosity=profile["verbosity"],
            evidence_depth=profile["evidence_depth"],
            escalation_sensitivity=profile["escalation_sensitivity"],
            proactive_throttle=profile["proactive_throttle"],
        )

        self._last_modifiers = modifiers

        level_icons = {
            TrustLevel.HIGH: "🟢",
            TrustLevel.NOMINAL: "🔵",
            TrustLevel.CAUTION: "🟡",
            TrustLevel.LOW: "🔴",
        }
        icon = level_icons.get(level, "⚪")
        logger.info(
            f"[TRUST_GOV] {icon} Level: {level.value} | "
            f"Score: {score:.3f} | "
            f"Confidence cap: {modifiers.confidence_ceiling} | "
            f"Throttle: {modifiers.proactive_throttle:.0%}"
        )

        return modifiers

    def apply_to_goals(self, goals: List[Any], building_id: str = "default") -> List[Any]:
        """
        Apply trust-weighted reasoning to a list of goals.

        - Caps confidence scores based on trust level
        - Filters proactive (non-critical) goals based on throttle rate
        - NEVER touches Terminal or Institutional severity goals

        Args:
            goals: List of ProactiveGoal objects
            building_id: Building to evaluate trust for

        Returns:
            Modified list of goals (same objects, modified in place)
        """
        modifiers = self.get_modifiers(building_id)

        dampened_count = 0
        throttled_count = 0
        immune_count = 0

        filtered_goals = []
        for i, goal in enumerate(goals):
            # ── Severity-based immunity: NEVER throttle critical goals ──
            goal_severity = getattr(goal, 'goal_type', '')
            goal_id = getattr(goal, 'goal_id', '')
            goal_priority = getattr(goal, 'priority', '')

            is_immune = (
                goal_severity in IMMUNE_SEVERITIES or
                goal_id.startswith("TERMINAL-") or
                goal_priority == "critical"
            )

            if is_immune:
                immune_count += 1
                filtered_goals.append(goal)
                continue

            # ── Confidence dampening ──
            original_conf = getattr(goal, 'confidence', 1.0)
            if original_conf > modifiers.confidence_ceiling:
                goal.confidence = modifiers.confidence_ceiling
                dampened_count += 1

            # ── Proactive throttling ──
            # Use deterministic throttle based on goal index
            # (not random — reproducible behavior)
            if modifiers.proactive_throttle > 0:
                # Throttle every Nth goal based on throttle rate
                # e.g., 0.25 throttle = skip every 4th non-immune goal
                throttle_interval = int(1.0 / modifiers.proactive_throttle) if modifiers.proactive_throttle > 0 else 999
                non_immune_index = i - immune_count
                if non_immune_index > 0 and non_immune_index % throttle_interval == 0:
                    throttled_count += 1
                    continue  # Skip this goal

            filtered_goals.append(goal)

        if dampened_count > 0 or throttled_count > 0:
            print(
                f"[TRUST_GOV] Applied: {dampened_count} dampened "
                f"(cap={modifiers.confidence_ceiling}), "
                f"{throttled_count} throttled, "
                f"{immune_count} immune"
            )

        return filtered_goals

    def should_throttle_proactive(self, building_id: str = "default") -> bool:
        """
        Quick check: should ARVIS reduce proactive suggestions right now?

        Used by the BriefingScheduler to decide whether to include
        low-priority suggestions in the daily briefing.
        """
        modifiers = self.get_modifiers(building_id)
        return modifiers.proactive_throttle > 0

    def get_briefing_context(self, building_id: str = "default") -> Dict[str, Any]:
        """
        Get trust context for inclusion in daily briefings.

        Returns a dict that can be injected into briefing templates.
        """
        modifiers = self.get_modifiers(building_id)
        return {
            "trust_status": modifiers.trust_level.value,
            "trust_score": modifiers.trust_score,
            "verbosity_mode": modifiers.verbosity.value,
            "evidence_signals_required": modifiers.evidence_depth,
            "confidence_ceiling": modifiers.confidence_ceiling,
            "proactive_throttle_pct": f"{modifiers.proactive_throttle:.0%}",
        }
