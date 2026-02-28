"""
Integrity Monitor — Active Greenwashing Detection
===================================================

Transforms the passive `[SILENT_FAIL] GSAS/Energy Divergence` check
into a 4-stage escalation system that treats persistent ESG
certification divergence as institutional risk.

Escalation Ladder:
  1. OBSERVATION  — First divergence: log only
  2. PATTERN      — 2nd divergence: flag in daily briefing  
  3. RISK         — 3rd divergence: named institutional risk
  4. INSTITUTIONAL — Persistent (N consecutive): "ESG certification
                     may not reflect operational reality"

CRITICAL: Level 4 requires directional divergence (GSAS ↑ while
Energy ↑), not random fluctuation or single anomaly.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Dict, Any, Optional, List

logger = logging.getLogger("arvis.advisory.integrity")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class EscalationLevel(IntEnum):
    """4-stage escalation ladder."""
    OBSERVATION = 1     # First divergence: log only
    PATTERN = 2         # Second divergence: flag in briefing
    RISK = 3            # Third divergence: named institutional risk
    INSTITUTIONAL = 4   # Persistent: ESG certification questionable


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DivergenceEvent:
    """A single observed GSAS/Energy divergence."""
    timestamp: datetime
    gsas_score: float
    energy_intensity: float
    gsas_delta: float       # Change from previous period
    energy_delta: float     # Change from previous period
    day: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "gsas_score": self.gsas_score,
            "energy_intensity": round(self.energy_intensity, 1),
            "gsas_delta": round(self.gsas_delta, 2),
            "energy_delta": round(self.energy_delta, 1),
            "day": self.day,
        }


@dataclass
class IntegrityAlert:
    """
    An active integrity alert at a specific escalation level.
    
    Level 4 (INSTITUTIONAL) requires executive visibility — this is
    not a suggestion, it's a statement about certification validity.
    """
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    building_id: str = ""
    level: EscalationLevel = EscalationLevel.OBSERVATION
    evidence: List[DivergenceEvent] = field(default_factory=list)
    consecutive_divergences: int = 0
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_updated_at: datetime = field(default_factory=datetime.now)
    requires_executive_visibility: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "building_id": self.building_id,
            "level": self.level.name,
            "level_value": self.level.value,
            "consecutive_divergences": self.consecutive_divergences,
            "recommendation": self.recommendation,
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() for e in self.evidence[-5:]],  # Last 5
            "created_at": self.created_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
            "requires_executive_visibility": self.requires_executive_visibility,
        }


# ═══════════════════════════════════════════════════════════════════════════
# GREENWASHING DETECTOR
# ═══════════════════════════════════════════════════════════════════════════

class GreenwashingDetector:
    """
    4-stage escalation detector for ESG certification divergence.

    Detects when GSAS scores improve (or stay stable) while energy
    intensity worsens — the hallmark of greenwashing.

    INVARIANT: Level 4 escalation requires DIRECTIONAL divergence
    over N consecutive periods, not random noise.
    """

    # Configuration
    DIVERGENCE_THRESHOLD_ENERGY = 2.0    # Minimum energy increase (kWh/m²)
    DIRECTIONAL_DAYS_FOR_L4 = 3          # Consecutive days needed for Level 4
    GSAS_TOLERANCE = 0.5                 # GSAS must improve by at least this

    def __init__(self):
        # Active alerts keyed by building_id
        self._alerts: Dict[str, IntegrityAlert] = {}
        # History of divergence events keyed by building_id
        self._history: Dict[str, List[DivergenceEvent]] = {}
        # Track previous values for delta calculation
        self._prev_values: Dict[str, Dict[str, float]] = {}

        logger.info("[INTEGRITY] Greenwashing Detector initialized (4-stage escalation)")

    def evaluate(
        self,
        gsas_score: float,
        energy_intensity: float,
        building_id: str = "default",
        day: int = 0,
        sim_time: Optional[datetime] = None,
    ) -> Optional[IntegrityAlert]:
        """
        Evaluate current GSAS and energy metrics for divergence.

        Returns IntegrityAlert if a divergence is detected or an
        existing alert is escalated. Returns None if metrics are
        consistent.
        """
        timestamp = sim_time or datetime.now()

        # Get previous values
        prev = self._prev_values.get(building_id, {})
        prev_gsas = prev.get("gsas_score")
        prev_energy = prev.get("energy_intensity")

        # Store current values for next evaluation
        self._prev_values[building_id] = {
            "gsas_score": gsas_score,
            "energy_intensity": energy_intensity,
        }

        # Can't evaluate on first reading
        if prev_gsas is None or prev_energy is None:
            return self._alerts.get(building_id)

        # Calculate deltas
        gsas_delta = gsas_score - prev_gsas
        energy_delta = energy_intensity - prev_energy

        # ── Divergence Detection ──
        # GSAS improves (or stable) AND energy worsens significantly
        is_divergent = (
            gsas_delta >= -self.GSAS_TOLERANCE  # GSAS not dropping much
            and energy_delta > self.DIVERGENCE_THRESHOLD_ENERGY  # Energy rising
        )

        # ── Directional divergence (stronger signal) ──
        # GSAS explicitly improves AND energy explicitly worsens
        is_directional = (
            gsas_delta > 0  # GSAS actually going up
            and energy_delta > self.DIVERGENCE_THRESHOLD_ENERGY  # Energy rising
        )

        if not is_divergent:
            # No divergence — reset consecutive counter if exists
            if building_id in self._alerts:
                alert = self._alerts[building_id]
                # Only reset if sustained non-divergence (allow single day gaps)
                if alert.consecutive_divergences > 0:
                    # Decay counter instead of hard reset
                    alert.consecutive_divergences = max(0, alert.consecutive_divergences - 1)
                    if alert.consecutive_divergences == 0 and alert.level <= EscalationLevel.PATTERN:
                        # Clear low-level alerts
                        del self._alerts[building_id]
                        logger.info(f"[INTEGRITY] ✅ Divergence cleared for {building_id}")
            return self._alerts.get(building_id)

        # ── Record divergence event ──
        event = DivergenceEvent(
            timestamp=timestamp,
            gsas_score=gsas_score,
            energy_intensity=energy_intensity,
            gsas_delta=gsas_delta,
            energy_delta=energy_delta,
            day=day,
        )

        if building_id not in self._history:
            self._history[building_id] = []
        self._history[building_id].append(event)

        # ── Escalation Logic ──
        if building_id not in self._alerts:
            # Level 1: First divergence — OBSERVATION
            alert = IntegrityAlert(
                building_id=building_id,
                level=EscalationLevel.OBSERVATION,
                evidence=[event],
                consecutive_divergences=1,
                recommendation="Monitor GSAS certification methodology against operational metrics.",
                created_at=timestamp,
                last_updated_at=timestamp,
            )
            self._alerts[building_id] = alert
            logger.info(
                f"[INTEGRITY] 📋 L1 OBSERVATION for {building_id} | "
                f"GSAS Δ={gsas_delta:+.1f}, Energy Δ={energy_delta:+.1f}"
            )
            print(
                f"[INTEGRITY] 📋 L1 OBSERVATION: GSAS/Energy divergence detected "
                f"(GSAS {gsas_delta:+.1f}, Energy {energy_delta:+.1f} kWh/m²)"
            )
            return alert

        # Existing alert — escalate
        alert = self._alerts[building_id]
        alert.evidence.append(event)
        alert.consecutive_divergences += 1
        alert.last_updated_at = timestamp

        # Level 2: PATTERN (2nd divergence)
        if alert.consecutive_divergences >= 2 and alert.level < EscalationLevel.PATTERN:
            alert.level = EscalationLevel.PATTERN
            alert.recommendation = (
                "GSAS certification shows repeated divergence from operational metrics. "
                "Include in daily briefing for operator awareness."
            )
            logger.info(f"[INTEGRITY] ⚠️ L2 PATTERN for {building_id} | {alert.consecutive_divergences} divergences")
            print(f"[INTEGRITY] ⚠️ L2 PATTERN: Repeated GSAS/Energy divergence ({alert.consecutive_divergences} events)")

        # Level 3: RISK (3rd divergence)
        elif alert.consecutive_divergences >= 3 and alert.level < EscalationLevel.RISK:
            alert.level = EscalationLevel.RISK
            alert.recommendation = (
                "ESG compliance data is consistently diverging from operational reality. "
                "This constitutes a named institutional risk: 'ESG Reporting Integrity'."
            )
            logger.warning(f"[INTEGRITY] 🔴 L3 RISK for {building_id} | {alert.consecutive_divergences} divergences")
            print(f"[INTEGRITY] 🔴 L3 RISK: ESG Reporting Integrity risk identified ({alert.consecutive_divergences} events)")

        # Level 4: INSTITUTIONAL (N consecutive directional divergences)
        elif (
            alert.consecutive_divergences >= self.DIRECTIONAL_DAYS_FOR_L4
            and alert.level < EscalationLevel.INSTITUTIONAL
            and self._has_directional_streak(building_id)
        ):
            alert.level = EscalationLevel.INSTITUTIONAL
            alert.requires_executive_visibility = True
            alert.recommendation = (
                "ESG certification may not reflect operational reality. "
                "GSAS scores have improved while energy intensity has worsened "
                f"for {alert.consecutive_divergences} consecutive evaluation periods. "
                "This requires executive visibility and potential audit of certification methodology."
            )
            logger.critical(
                f"[INTEGRITY] 🚨 L4 INSTITUTIONAL for {building_id} | "
                f"{alert.consecutive_divergences} consecutive directional divergences"
            )
            print(
                f"[INTEGRITY] 🚨 L4 INSTITUTIONAL: ESG certification may not reflect reality. "
                f"Executive visibility required."
            )

        return alert

    def get_escalation_level(self, building_id: str) -> Optional[EscalationLevel]:
        """Get current escalation level for a building."""
        alert = self._alerts.get(building_id)
        return alert.level if alert else None

    def get_active_alerts(self, building_id: str = None) -> List[IntegrityAlert]:
        """Get active integrity alerts, optionally filtered by building."""
        if building_id:
            alert = self._alerts.get(building_id)
            return [alert] if alert else []
        return list(self._alerts.values())

    def get_briefing_alerts(self, building_id: str) -> List[IntegrityAlert]:
        """Get alerts that should be included in daily briefings (Level 2+)."""
        alerts = self.get_active_alerts(building_id)
        return [a for a in alerts if a.level >= EscalationLevel.PATTERN]

    def _has_directional_streak(self, building_id: str) -> bool:
        """
        Check if the last N events show directional divergence
        (GSAS actually going UP while energy going UP).

        This prevents Level 4 escalation on noise or single anomalies.
        """
        history = self._history.get(building_id, [])
        if len(history) < self.DIRECTIONAL_DAYS_FOR_L4:
            return False

        recent = history[-self.DIRECTIONAL_DAYS_FOR_L4:]
        return all(
            e.gsas_delta > 0 and e.energy_delta > self.DIVERGENCE_THRESHOLD_ENERGY
            for e in recent
        )
