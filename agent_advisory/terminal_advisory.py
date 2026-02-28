"""
Terminal Advisory Engine
========================

Issues hard advisory boundaries when a building system exceeds its
safe operating envelope.  A Terminal Advisory is NOT a recommendation
— it is a formal declaration that:

  - Cannot be dismissed without operator acknowledgment + reason code
  - Cannot be suppressed by the conflict resolver
  - Cannot be throttled by the trust governor
  - Persists (idempotent) until the condition clears or is acknowledged

SafetyEnvelope values are OEM / ISO limits, not learned thresholds.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional, List

logger = logging.getLogger("arvis.advisory.terminal")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class AdvisorySeverity(Enum):
    """Severity of a terminal advisory declaration."""
    WARNING = "warning"       # Approaching envelope boundary
    CRITICAL = "critical"     # At boundary — immediate action needed
    TERMINAL = "terminal"     # Beyond boundary — cannot operate safely


class EnvelopeParameter(Enum):
    """Parameters monitored by the safety envelope."""
    CHILLER_VIBRATION = "chiller_vibration"
    OUTDOOR_TEMP = "outdoor_temp"
    CHILLER_COP = "chiller_cop"
    DISCHARGE_TEMP = "discharge_temp"
    CONTINUOUS_RUN_HOURS = "continuous_run_hours"


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SafetyEnvelope:
    """
    OEM / ISO limits per equipment type.

    These are deterministic, engineering-defined limits — NOT learned
    thresholds.  Each limit has a warning threshold (~85% of max) and
    a terminal threshold (the actual OEM limit).
    """
    # Vibration (ISO 10816 — continuous operation limit)
    chiller_vib_warning: float = 2.8       # mm/s — 80% of limit
    chiller_vib_max: float = 3.5           # mm/s — trip threshold

    # Ambient Temperature (Gulf condenser design limit)
    outdoor_temp_warning: float = 48.0     # °C
    outdoor_temp_max: float = 52.0         # °C

    # COP (below = compressor thermal stress)
    chiller_cop_warning: float = 2.2
    chiller_cop_min: float = 1.8

    # Discharge Temperature (compressor discharge — oil degradation)
    discharge_temp_warning: float = 95.0   # °C
    discharge_temp_max: float = 110.0      # °C

    # Continuous Runtime (thermal stacking risk)
    run_hours_warning: int = 16            # hours at >90% load
    run_hours_max: int = 20               # hours — must rest

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chiller_vib": {"warning": self.chiller_vib_warning, "max": self.chiller_vib_max},
            "outdoor_temp": {"warning": self.outdoor_temp_warning, "max": self.outdoor_temp_max},
            "chiller_cop": {"warning": self.chiller_cop_warning, "min": self.chiller_cop_min},
            "discharge_temp": {"warning": self.discharge_temp_warning, "max": self.discharge_temp_max},
            "continuous_run_hours": {"warning": self.run_hours_warning, "max": self.run_hours_max},
        }


@dataclass
class EnvelopeBreach:
    """A single parameter breach within the safety envelope."""
    parameter: EnvelopeParameter
    current_value: float
    limit_value: float
    severity: AdvisorySeverity
    margin_pct: float  # How far past the limit (negative = within)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter.value,
            "current": self.current_value,
            "limit": self.limit_value,
            "severity": self.severity.value,
            "margin_pct": round(self.margin_pct, 1),
        }


@dataclass
class TerminalAdvisory:
    """
    Formal boundary declaration.

    This is NOT a recommendation.  It is a statement of fact:
    "This system cannot be operated safely beyond X hours."

    Requires operator acknowledgment with a reason code.
    Idempotent — persists and reaffirms across cycles.
    """
    advisory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    building_id: str = ""
    severity: AdvisorySeverity = AdvisorySeverity.WARNING
    breaches: List[EnvelopeBreach] = field(default_factory=list)
    time_to_breach_hours: Optional[float] = None
    summary: str = ""
    affected_equipment: List[str] = field(default_factory=list)

    # Idempotency — tracks persistence across cycles
    first_declared_at: datetime = field(default_factory=datetime.now)
    last_reaffirmed_at: datetime = field(default_factory=datetime.now)
    reaffirmation_count: int = 0

    # Acknowledgment
    requires_acknowledgment: bool = True
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_reason: Optional[str] = None

    @property
    def active_duration(self) -> timedelta:
        """How long this advisory has been active."""
        return datetime.now() - self.first_declared_at

    @property
    def active_duration_str(self) -> str:
        """Human-readable duration string."""
        delta = self.active_duration
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m"
        return f"{hours:.0f}h {int(delta.seconds % 3600 / 60)}m"

    def reaffirm(self):
        """Reaffirm this advisory for another cycle (idempotent)."""
        self.last_reaffirmed_at = datetime.now()
        self.reaffirmation_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "advisory_id": self.advisory_id,
            "building_id": self.building_id,
            "severity": self.severity.value,
            "summary": self.summary,
            "breaches": [b.to_dict() for b in self.breaches],
            "time_to_breach_hours": self.time_to_breach_hours,
            "affected_equipment": self.affected_equipment,
            "first_declared_at": self.first_declared_at.isoformat(),
            "last_reaffirmed_at": self.last_reaffirmed_at.isoformat(),
            "reaffirmation_count": self.reaffirmation_count,
            "active_duration": self.active_duration_str,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_reason": self.acknowledged_reason,
        }


# ═══════════════════════════════════════════════════════════════════════════
# TERMINAL ADVISORY ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TerminalAdvisoryEngine:
    """
    Evaluates building state against the safety envelope and issues
    formal terminal advisory declarations.

    - Idempotent: same breach → reaffirm existing advisory (not new)
    - Non-suppressible: TERMINAL goals bypass conflict resolver
    - Non-throttlable: bypass trust governor
    """

    def __init__(self, envelope: Optional[SafetyEnvelope] = None):
        self.envelope = envelope or SafetyEnvelope()
        # Active advisories keyed by building_id
        self._active: Dict[str, TerminalAdvisory] = {}
        logger.info("[TERMINAL] Advisory Engine initialized with OEM envelope")

    def evaluate(self, state: Dict[str, Any], building_id: str = "default") -> Optional[TerminalAdvisory]:
        """
        Evaluate the current building state against the safety envelope.

        Returns:
            TerminalAdvisory if any parameter breaches warning/critical/terminal,
            None if all parameters are within the safe envelope.
        """
        breaches = self._check_all_parameters(state)

        if not breaches:
            # All clear — clear any existing advisory
            if building_id in self._active:
                cleared = self._active.pop(building_id)
                logger.info(
                    f"[TERMINAL] ✅ Advisory CLEARED for {building_id} "
                    f"(was active {cleared.active_duration_str})"
                )
            return None

        # Determine overall severity (highest breach wins)
        severity_order = {
            AdvisorySeverity.WARNING: 1,
            AdvisorySeverity.CRITICAL: 2,
            AdvisorySeverity.TERMINAL: 3,
        }
        overall_severity = max(breaches, key=lambda b: severity_order[b.severity]).severity

        # Build summary
        summary = self._build_summary(breaches, overall_severity, state)

        # Estimate time to breach (simple linear extrapolation)
        ttb = self._estimate_time_to_breach(breaches, state)

        # Equipment affected
        equipment = self._identify_affected_equipment(breaches)

        # ── Idempotency: reaffirm or create ──
        if building_id in self._active:
            existing = self._active[building_id]
            existing.severity = overall_severity
            existing.breaches = breaches
            existing.summary = summary
            existing.time_to_breach_hours = ttb
            existing.affected_equipment = equipment
            existing.reaffirm()
            logger.info(
                f"[TERMINAL] 🔄 Advisory REAFFIRMED for {building_id} | "
                f"Severity: {overall_severity.value.upper()} | "
                f"Active: {existing.active_duration_str} | "
                f"Reaffirmations: {existing.reaffirmation_count}"
            )
            return existing

        # New advisory
        advisory = TerminalAdvisory(
            building_id=building_id,
            severity=overall_severity,
            breaches=breaches,
            time_to_breach_hours=ttb,
            summary=summary,
            affected_equipment=equipment,
        )
        self._active[building_id] = advisory

        severity_icons = {"warning": "⚠️", "critical": "🔴", "terminal": "🚨"}
        icon = severity_icons.get(overall_severity.value, "❓")
        logger.info(
            f"[TERMINAL] {icon} NEW advisory DECLARED for {building_id} | "
            f"Severity: {overall_severity.value.upper()}"
        )
        print(
            f"[TERMINAL] {icon} {overall_severity.value.upper()} — {summary}"
        )

        return advisory

    def acknowledge(
        self,
        building_id: str,
        operator_id: str,
        reason_code: str
    ) -> bool:
        """
        Acknowledge a terminal advisory.

        Args:
            building_id: Building with the active advisory
            operator_id: Who is acknowledging
            reason_code: Why they are proceeding despite the advisory

        Returns:
            True if acknowledged, False if no active advisory
        """
        advisory = self._active.get(building_id)
        if not advisory:
            logger.warning(f"[TERMINAL] No active advisory for {building_id}")
            return False

        advisory.acknowledged = True
        advisory.acknowledged_by = operator_id
        advisory.acknowledged_at = datetime.now()
        advisory.acknowledged_reason = reason_code

        logger.info(
            f"[TERMINAL] Advisory ACKNOWLEDGED by {operator_id} | "
            f"Reason: {reason_code} | Building: {building_id}"
        )
        return True

    def get_active_advisory(self, building_id: str) -> Optional[TerminalAdvisory]:
        """Get the currently active advisory for a building, if any."""
        return self._active.get(building_id)

    def has_active_advisory(self, building_id: str) -> bool:
        """Check if a building has an active advisory."""
        return building_id in self._active

    # ── Internal Methods ──────────────────────────────────────────────

    def _check_all_parameters(self, state: Dict[str, Any]) -> List[EnvelopeBreach]:
        """Check all envelope parameters against current state."""
        breaches = []

        # 1. Chiller Vibration
        for key in ["chiller_01_vib", "chiller_02_vib"]:
            vib = state.get(key, 0)
            if vib > 0:
                breach = self._check_parameter(
                    param=EnvelopeParameter.CHILLER_VIBRATION,
                    value=vib,
                    warning=self.envelope.chiller_vib_warning,
                    limit=self.envelope.chiller_vib_max,
                    higher_is_worse=True,
                )
                if breach:
                    breaches.append(breach)

        # 2. Outdoor Temperature
        temp = state.get("outdoor_temp", 0)
        if temp > 0:
            breach = self._check_parameter(
                param=EnvelopeParameter.OUTDOOR_TEMP,
                value=temp,
                warning=self.envelope.outdoor_temp_warning,
                limit=self.envelope.outdoor_temp_max,
                higher_is_worse=True,
            )
            if breach:
                breaches.append(breach)

        # 3. Chiller COP (inverted — lower is worse)
        cop = state.get("chiller_cop", 99)
        if cop < 10:  # Sanity check
            breach = self._check_parameter(
                param=EnvelopeParameter.CHILLER_COP,
                value=cop,
                warning=self.envelope.chiller_cop_warning,
                limit=self.envelope.chiller_cop_min,
                higher_is_worse=False,
            )
            if breach:
                breaches.append(breach)

        # 4. Discharge Temperature
        discharge = state.get("discharge_temp", 0)
        if discharge > 0:
            breach = self._check_parameter(
                param=EnvelopeParameter.DISCHARGE_TEMP,
                value=discharge,
                warning=self.envelope.discharge_temp_warning,
                limit=self.envelope.discharge_temp_max,
                higher_is_worse=True,
            )
            if breach:
                breaches.append(breach)

        # 5. Continuous Run Hours
        run_hours = state.get("continuous_run_hours", 0)
        if run_hours > 0:
            breach = self._check_parameter(
                param=EnvelopeParameter.CONTINUOUS_RUN_HOURS,
                value=run_hours,
                warning=self.envelope.run_hours_warning,
                limit=self.envelope.run_hours_max,
                higher_is_worse=True,
            )
            if breach:
                breaches.append(breach)

        return breaches

    def _check_parameter(
        self,
        param: EnvelopeParameter,
        value: float,
        warning: float,
        limit: float,
        higher_is_worse: bool,
    ) -> Optional[EnvelopeBreach]:
        """
        Check a single parameter against warning and limit thresholds.

        Returns EnvelopeBreach if breached, None if within envelope.
        """
        if higher_is_worse:
            if value >= limit:
                margin = ((value - limit) / limit) * 100
                return EnvelopeBreach(
                    parameter=param, current_value=value, limit_value=limit,
                    severity=AdvisorySeverity.TERMINAL, margin_pct=margin,
                )
            elif value >= warning:
                margin = ((value - warning) / warning) * 100
                return EnvelopeBreach(
                    parameter=param, current_value=value, limit_value=limit,
                    severity=AdvisorySeverity.CRITICAL if value >= (warning + limit) / 2 else AdvisorySeverity.WARNING,
                    margin_pct=margin,
                )
        else:
            # Inverted (lower is worse) — e.g., COP
            if value <= limit:
                margin = ((limit - value) / limit) * 100
                return EnvelopeBreach(
                    parameter=param, current_value=value, limit_value=limit,
                    severity=AdvisorySeverity.TERMINAL, margin_pct=margin,
                )
            elif value <= warning:
                margin = ((warning - value) / warning) * 100
                return EnvelopeBreach(
                    parameter=param, current_value=value, limit_value=limit,
                    severity=AdvisorySeverity.CRITICAL if value <= (warning + limit) / 2 else AdvisorySeverity.WARNING,
                    margin_pct=margin,
                )

        return None  # Within envelope

    def _build_summary(
        self,
        breaches: List[EnvelopeBreach],
        severity: AdvisorySeverity,
        state: Dict[str, Any],
    ) -> str:
        """Build a human-readable summary of the terminal advisory."""
        parts = []
        for b in breaches:
            param_names = {
                EnvelopeParameter.CHILLER_VIBRATION: "Chiller vibration",
                EnvelopeParameter.OUTDOOR_TEMP: "Outdoor temperature",
                EnvelopeParameter.CHILLER_COP: "Chiller COP",
                EnvelopeParameter.DISCHARGE_TEMP: "Compressor discharge temp",
                EnvelopeParameter.CONTINUOUS_RUN_HOURS: "Continuous runtime",
            }
            name = param_names.get(b.parameter, b.parameter.value)
            direction = "above" if b.current_value > b.limit_value else "below"
            parts.append(f"{name} {b.current_value:.1f} ({direction} {b.limit_value:.1f} limit)")

        breach_text = "; ".join(parts)

        if severity == AdvisorySeverity.TERMINAL:
            return (
                f"System beyond safe operating envelope. {breach_text}. "
                f"This is not a recommendation — this is a boundary declaration."
            )
        elif severity == AdvisorySeverity.CRITICAL:
            return (
                f"Approaching safe operating limit. {breach_text}. "
                f"Immediate operator attention required."
            )
        else:
            return f"Safety envelope warning. {breach_text}."

    def _estimate_time_to_breach(
        self, breaches: List[EnvelopeBreach], state: Dict[str, Any]
    ) -> Optional[float]:
        """
        Estimate hours until the most critical parameter exceeds its limit.

        Uses simple linear extrapolation from current rate of change.
        Returns None if already breached or cannot estimate.
        """
        # For terminal breaches, we're already past the limit
        terminal_breaches = [b for b in breaches if b.severity == AdvisorySeverity.TERMINAL]
        if terminal_breaches:
            return 0.0  # Already beyond envelope

        # For warning/critical, estimate based on typical degradation rates
        # Conservative estimates per phase context
        min_hours = float("inf")
        for b in breaches:
            if b.parameter == EnvelopeParameter.CHILLER_VIBRATION:
                # Typical degradation: 0.1 mm/s per day under stress
                remaining = b.limit_value - b.current_value
                hours = max(1, (remaining / 0.1) * 24)
                min_hours = min(min_hours, hours)
            elif b.parameter == EnvelopeParameter.OUTDOOR_TEMP:
                # Weather driven — harder to estimate, use 12h as conservative
                min_hours = min(min_hours, 12.0)
            elif b.parameter == EnvelopeParameter.CHILLER_COP:
                remaining = b.current_value - b.limit_value
                hours = max(1, (remaining / 0.05) * 24)
                min_hours = min(min_hours, hours)

        return min_hours if min_hours < float("inf") else None

    def _identify_affected_equipment(self, breaches: List[EnvelopeBreach]) -> List[str]:
        """Identify equipment affected by the breaches."""
        equipment = set()
        for b in breaches:
            if b.parameter == EnvelopeParameter.CHILLER_VIBRATION:
                equipment.add("CH-01")
                equipment.add("CH-02")
            elif b.parameter in (EnvelopeParameter.CHILLER_COP, EnvelopeParameter.DISCHARGE_TEMP):
                equipment.add("CH-01")
            elif b.parameter == EnvelopeParameter.OUTDOOR_TEMP:
                equipment.add("CONDENSER-01")
                equipment.add("CONDENSER-02")
            elif b.parameter == EnvelopeParameter.CONTINUOUS_RUN_HOURS:
                equipment.add("CH-01")
        return sorted(equipment)
