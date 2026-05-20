import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _comfort_risk_from_complaints(complaints_pct: float) -> str:
    """Map predicted complaint percentage to a GSAS-compatible risk label."""
    if complaints_pct < 3.0:
        return "low"
    if complaints_pct < 8.0:
        return "medium"
    return "high"


def _extract_change_values(action: Dict[str, Any], change_type: str):
    """
    Pull current_value / proposed_value out of the action dict.

    Priority:
      1. Explicit ``current_value`` / ``proposed_value`` keys on the action.
      2. Reconstruct from ``value_delta`` (proposed = current + delta).
      3. Default to Qatar-typical HVAC setpoint range (22 °C baseline).

    Returns (current_value, proposed_value) as floats.
    """
    current = action.get("current_value")
    proposed = action.get("proposed_value")

    if current is not None and proposed is not None:
        return float(current), float(proposed)

    if change_type == "setpoint":
        # Setpoints: default baseline 22 °C
        current = float(action.get("current_value", 22.0))
        delta = float(action.get("value_delta", 1.0))
        proposed = current + delta
    else:
        # runtime_reduction: represent as 0–100 % runtime, default full → 80 %
        current = float(action.get("current_value", 100.0))
        delta = float(action.get("value_delta", -20.0))
        proposed = current + delta

    return current, proposed


# ---------------------------------------------------------------------------
# ComfortPredictor
# ---------------------------------------------------------------------------

class ComfortPredictor:
    """
    Estimates the thermal and indoor air quality comfort impact of proposed
    BMS actions before they are executed.

    When an ``MLSimulator`` is injected *and* already trained, predictions are
    derived from ``MLSimulator.simulate_with_uncertainty()``.  If the simulator
    is unavailable, untrained, or raises an exception the predictor falls back
    to the deterministic physics rules that were present in the original
    implementation.
    """

    # Approximate PMV-unit → °C conversion used when mapping ML comfort output
    PMV_TO_DEG_C = 0.5

    def __init__(self, simulator: Optional[Any] = None):
        self.simulator = simulator

        # Simple adjacency map for thermal bleed modelling
        self.adjacency_map: Dict[str, List[str]] = {
            "floor_7_zone_a": ["floor_7_zone_b", "floor_7_corridor"],
            "floor_7_zone_b": ["floor_7_zone_a", "floor_7_corridor"],
            "floor_8_zone_a": ["floor_8_zone_b", "floor_8_corridor"],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_impact(
        self,
        action: Dict[str, Any],
        zone_id: str,
        outdoor_temp: float = 35.0,
    ) -> Dict[str, Any]:
        """
        Project how a specific action will affect comfort in the target zone
        and its adjacent zones.

        Args:
            action:       Dict describing the action, e.g.
                          ``{"type": "reduce_runtime", "equipment": "AHU-7A"}``
            zone_id:      The primary zone affected.
            outdoor_temp: Outdoor dry-bulb temperature in °C.
                          Defaults to 35 °C (Qatar year-round typical).

        Returns:
            Dict with keys:
              primary_zone, delta_temp_c, adjacent_zones_affected,
              adjacent_delta_temp_c, comfort_risk, gsas_ie1_impact,
              prediction_confidence
        """
        logger.debug(
            "Predicting comfort impact of '%s' on %s (outdoor %.1f °C)",
            action.get("type"),
            zone_id,
            outdoor_temp,
        )

        action_type = action.get("type", "")
        adjacent_zones = self.adjacency_map.get(zone_id, [])

        # ------------------------------------------------------------------
        # Attempt ML path
        # ------------------------------------------------------------------
        ml_result = self._try_ml_prediction(action, action_type, outdoor_temp)

        if ml_result is not None:
            delta_temp_c, comfort_risk, ie1_impact, confidence = ml_result
        else:
            delta_temp_c, comfort_risk, ie1_impact, confidence = (
                self._physics_prediction(action, action_type)
            )

        return {
            "primary_zone": zone_id,
            "delta_temp_c": delta_temp_c,
            "adjacent_zones_affected": adjacent_zones,
            "adjacent_delta_temp_c": round(delta_temp_c * 0.2, 2),  # 20 % bleed
            "comfort_risk": comfort_risk,
            "gsas_ie1_impact": ie1_impact,
            "prediction_confidence": confidence,
        }

    # ------------------------------------------------------------------
    # ML prediction path
    # ------------------------------------------------------------------

    def _try_ml_prediction(
        self,
        action: Dict[str, Any],
        action_type: str,
        outdoor_temp: float,
    ):
        """
        Attempt to call ``MLSimulator.simulate_with_uncertainty()``.

        Returns a 4-tuple ``(delta_temp_c, comfort_risk, ie1_impact,
        confidence)`` on success, or ``None`` if ML is unavailable.

        The method never raises; any exception is caught, logged, and ``None``
        is returned so the caller can fall back to physics rules.
        """
        if self.simulator is None:
            return None

        if not getattr(self.simulator, "is_trained", False):
            logger.debug("MLSimulator not yet trained – using physics fallback")
            return None

        # Map BMS action type to MLSimulator change_type vocabulary
        change_type = self._map_action_to_change_type(action_type)
        if change_type is None:
            # No ML analogue for this action (e.g. economizer, ventilation)
            return None

        current_value, proposed_value = _extract_change_values(action, change_type)

        try:
            result = self.simulator.simulate_with_uncertainty(
                change={
                    "change_type": change_type,
                    "current_value": current_value,
                    "proposed_value": proposed_value,
                },
                outdoor_temp=outdoor_temp,
                n_monte_carlo=200,  # Faster for real-time path
            )
        except Exception as exc:
            logger.warning(
                "MLSimulator.simulate_with_uncertainty() raised %s – "
                "falling back to physics rules",
                exc,
            )
            return None

        # ---------------------------------------------------------------
        # Derive comfort scalars from MLSimulationResult
        # ---------------------------------------------------------------
        # ``comfort_impact.mean`` is predicted complaint percentage
        # (from the simulator's model: complaints_pct ≈ delta_setpoint * 5).
        # We invert that to get an approximate PMV delta, then convert to °C.
        complaints_pct: float = result.comfort_impact.mean

        # PMV delta ≈ complaints% / 5  (inverse of simulator's forward model)
        thermal_comfort_delta: float = complaints_pct / 5.0

        # °C equivalent via PMV_TO_DEG_C conversion factor
        delta_temp_c = round(thermal_comfort_delta * self.PMV_TO_DEG_C, 2)

        comfort_risk = _comfort_risk_from_complaints(complaints_pct)

        # GSAS IE.1 impact: penalise medium/high risk, reward low-risk actions
        ie1_impact = self._gsas_ie1_from_risk(comfort_risk, result)

        # Confidence from the ML energy model
        confidence = float(result.energy_impact.confidence)

        logger.debug(
            "ML prediction: delta_temp=%.2f°C  comfort_risk=%s  "
            "confidence=%.3f  model=%s",
            delta_temp_c,
            comfort_risk,
            confidence,
            result.model_used,
        )
        return delta_temp_c, comfort_risk, ie1_impact, confidence

    # ------------------------------------------------------------------
    # Physics / rule-based fallback (original logic, unchanged)
    # ------------------------------------------------------------------

    def _physics_prediction(
        self,
        action: Dict[str, Any],
        action_type: str,
    ):
        """
        Original rule-based prediction.  Used when ML is unavailable or
        the action type has no ML analogue.

        Returns (delta_temp_c, comfort_risk, ie1_impact, confidence).
        """
        delta_temp_c = 0.0
        risk_level = "low"
        ie1_impact = 0.0

        if "setpoint" in action_type:
            delta_temp_c = float(action.get("value_delta", 1.0))
            if abs(delta_temp_c) > 1.5:
                risk_level = "medium"
                ie1_impact = -0.05

        elif "reduce_runtime" in action_type or "shutdown" in action_type:
            delta_temp_c = 0.8  # Expected drift during unoccupied period
            if action.get("during_occupancy", False):
                risk_level = "high"
                ie1_impact = -0.5
            else:
                risk_level = "low"
                ie1_impact = 0.0  # No GSAS penalty if unoccupied

        elif "economizer" in action_type:
            delta_temp_c = 0.2
            risk_level = "low"
            ie1_impact = +0.02

        return delta_temp_c, risk_level, ie1_impact, 0.85

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_action_to_change_type(action_type: str) -> Optional[str]:
        """
        Translate BMS action type strings to the MLSimulator's ``change_type``
        vocabulary (``"setpoint"`` or ``"runtime_reduction"``).

        Returns ``None`` for action types that have no ML analogue (the physics
        fallback will handle them instead).
        """
        if "setpoint" in action_type:
            return "setpoint"
        if "reduce_runtime" in action_type or "shutdown" in action_type:
            return "runtime_reduction"
        # economizer, ventilation, demand_limiting, filter_monitoring, etc.
        # – no direct ML analogue; defer to physics rules
        return None

    @staticmethod
    def _gsas_ie1_from_risk(
        comfort_risk: str,
        result: Any,
    ) -> float:
        """
        Map ML-derived comfort risk + reversion probability to a GSAS IE.1
        point-impact float.

        Convention (matches physics fallback scale):
          low    →  0.0   (neutral)
          medium → -0.05  (minor penalty)
          high   → -0.50  (significant penalty, equivalent to occupancy shutdown)
        """
        base: Dict[str, float] = {"low": 0.0, "medium": -0.05, "high": -0.50}
        score = base.get(comfort_risk, 0.0)

        # Apply a small additional discount proportional to reversion risk
        reversion_risk: float = getattr(result, "risk_of_reversion", 0.0)
        if reversion_risk > 0.3:
            score = min(score - 0.05, -0.05)

        return round(score, 3)
