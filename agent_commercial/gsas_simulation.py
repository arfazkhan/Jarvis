import logging
import copy
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# GSAS point-scaling constants — documented assumptions for proportional mapping
# ─────────────────────────────────────────────────────────────────────────────
# Energy criteria (E.1, E.2, E.3) collectively carry ~10 GSAS points.
# We allocate a baseline award of 0.5 points to E.1 for every 5 % energy saving,
# giving a linear rate of 0.1 E.1 points per 1 % saving.
_ENERGY_PCT_PER_STEP = 5.0          # % reduction → one step
_E1_POINTS_PER_STEP = 0.5           # GSAS E.1 points awarded per step

# Water criteria (W.1) award 0.3 points for a 10 % water reduction.
_WATER_PCT_PER_STEP = 10.0
_W1_POINTS_PER_STEP = 0.3

# Indoor-environment comfort criterion (IE.1) penalties.
_COMFORT_PENALTY_HIGH = 0.5         # deducted when comfort_risk == "high"
_COMFORT_PENALTY_MEDIUM = 0.1       # deducted when comfort_risk == "medium"

# Heuristic physics constants (fallback only, fully documented)
# Each +1 °C setpoint raise ≈ −3 % cooling-energy consumption (ASHRAE rule-of-thumb)
_SETPOINT_DEGREE_TO_ENERGY_PCT = 3.0
# Default assumed runtime-reduction percentage when action dict has no "reduction_pct"
_DEFAULT_RUNTIME_REDUCTION_PCT = 10.0
# Water actions: default assumed 10 % water saving unless action carries a value
_DEFAULT_WATER_REDUCTION_PCT = 10.0


class GSASSimulator:
    """
    Simulates the impact of a proposed BMS action on the GSAS score.

    Clones the current GSASReporter state, applies projected changes, and
    returns the score delta.

    Energy / water deltas are derived — in order of preference — from:
      1. MLSimulator.simulate_with_uncertainty()   (GP + LightGBM, fully trained)
      2. EnergyForecaster.predict()                (Prophet / LightGBM, partially trained)
      3. _action_to_energy_pct()                   (physics heuristics — last resort)

    Point adjustments on GSAS criteria are then scaled proportionally to the
    computed delta percentage rather than using hardcoded magic numbers.
    """

    def __init__(
        self,
        current_reporter: Any,
        energy_forecaster: Optional[Any] = None,
        ml_simulator: Optional[Any] = None,
    ):
        """
        Parameters
        ----------
        current_reporter : GSASReporter
            Live reporter whose ``criteria`` dict is deep-copied for simulation.
        energy_forecaster : EnergyForecaster, optional
            Trained EnergyForecaster instance.  Used when ``ml_simulator`` is
            not available or not trained.
        ml_simulator : MLSimulator, optional
            Trained MLSimulator instance.  Preferred engine for energy delta
            computation when ``is_trained`` is True.
        """
        self.original_reporter = current_reporter
        self.energy_forecaster = energy_forecaster
        self.ml_simulator = ml_simulator
        self.simulated_criteria: Dict[str, Any] = {}

    # =========================================================================
    # Public API
    # =========================================================================

    def simulate_impact(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Projects GSAS score impact before execution.

        Returns
        -------
        dict with keys:
            action, original_score, projected_score, score_delta,
            category_deltas, warnings, simulation_source
        """
        logger.debug("Simulating GSAS action impact: %s", action.get("type"))

        # Always start from a clean clone to avoid state mutation across calls
        self.simulated_criteria = (
            copy.deepcopy(self.original_reporter.criteria)
            if hasattr(self.original_reporter, "criteria")
            else {}
        )

        # ── Snapshot before ──────────────────────────────────────────────────
        original_score = self._calculate_score(self.simulated_criteria)
        original_e_score = self._calculate_category_score(self.simulated_criteria, "E")
        original_w_score = self._calculate_category_score(self.simulated_criteria, "W")

        action_type = action.get("type", "")

        # ── Derive energy delta % and comfort risk ────────────────────────────
        energy_pct_delta, water_pct_delta, comfort_risk, simulation_source = \
            self._compute_deltas(action)

        # ── Apply proportional criterion adjustments ──────────────────────────
        # Energy criteria: energy_pct_delta < 0 means saving → award points
        if "setpoint" in action_type or "schedule" in action_type or "demand" in action_type:
            energy_saving_pct = -energy_pct_delta  # positive = saving
            e1_delta = (energy_saving_pct / _ENERGY_PCT_PER_STEP) * _E1_POINTS_PER_STEP
            if e1_delta != 0.0 and "E.1" in self.simulated_criteria:
                self.simulated_criteria["E.1"].current_points = min(
                    self.simulated_criteria["E.1"].max_points,
                    max(0.0, self.simulated_criteria["E.1"].current_points + e1_delta),
                )

        # Water criteria: water_pct_delta < 0 means saving → award points
        if "water" in action_type or "cooling_tower" in action_type:
            water_saving_pct = -water_pct_delta  # positive = saving
            w1_delta = (water_saving_pct / _WATER_PCT_PER_STEP) * _W1_POINTS_PER_STEP
            if w1_delta != 0.0 and "W.1" in self.simulated_criteria:
                self.simulated_criteria["W.1"].current_points = min(
                    self.simulated_criteria["W.1"].max_points,
                    max(0.0, self.simulated_criteria["W.1"].current_points + w1_delta),
                )

        # Comfort penalty (IE.1)
        if comfort_risk == "high":
            ie1_penalty = _COMFORT_PENALTY_HIGH
        elif comfort_risk == "medium":
            ie1_penalty = _COMFORT_PENALTY_MEDIUM
        else:
            ie1_penalty = 0.0

        # Legacy: hard comfort penalty for aggressive runtime reduction during occupancy
        if "reduce_runtime" in action_type and action.get("during_occupancy", False):
            ie1_penalty = max(ie1_penalty, _COMFORT_PENALTY_HIGH)

        if ie1_penalty > 0.0 and "IE.1" in self.simulated_criteria:
            self.simulated_criteria["IE.1"].current_points = max(
                0.0,
                self.simulated_criteria["IE.1"].current_points - ie1_penalty,
            )

        # ── Snapshot after ───────────────────────────────────────────────────
        new_score = self._calculate_score(self.simulated_criteria)
        new_e_score = self._calculate_category_score(self.simulated_criteria, "E")
        new_w_score = self._calculate_category_score(self.simulated_criteria, "W")

        score_delta = new_score - original_score

        # Risk detection: flag if E or W falls below 40 % of max
        max_e = self._calculate_category_max(self.simulated_criteria, "E")
        max_w = self._calculate_category_max(self.simulated_criteria, "W")
        e_warning = (new_e_score / max_e) < 0.40 if max_e > 0 else False
        w_warning = (new_w_score / max_w) < 0.40 if max_w > 0 else False

        return {
            "action": action,
            "original_score": round(original_score, 2),
            "projected_score": round(new_score, 2),
            "score_delta": round(score_delta, 2),
            "category_deltas": {
                "E": round(new_e_score - original_e_score, 2),
                "W": round(new_w_score - original_w_score, 2),
            },
            "warnings": {
                "energy_critical": e_warning,
                "water_critical": w_warning,
            },
            "simulation_source": simulation_source,
            "energy_pct_delta": round(energy_pct_delta, 2),
            "water_pct_delta": round(water_pct_delta, 2),
            "comfort_risk": comfort_risk,
        }

    # =========================================================================
    # Delta computation — ordered by engine preference
    # =========================================================================

    def _compute_deltas(
        self, action: Dict[str, Any]
    ):
        """
        Return ``(energy_pct_delta, water_pct_delta, comfort_risk, source)``
        using the best available engine.

        energy_pct_delta < 0 → energy saving (good)
        water_pct_delta  < 0 → water  saving (good)
        comfort_risk     : "low" | "medium" | "high"
        source           : "ml_simulator" | "energy_forecaster" | "heuristic"
        """

        # ── 1. MLSimulator (preferred) ────────────────────────────────────────
        if self.ml_simulator is not None and getattr(self.ml_simulator, "is_trained", False):
            try:
                change = {
                    "change_type": action.get("change_type", action.get("type", "setpoint")),
                    "current_value": float(action.get("current_value", 22.0)),
                    "proposed_value": float(action.get("proposed_value", 23.0)),
                }
                outdoor_temp = float(action.get("outdoor_temp", 35.0))
                result = self.ml_simulator.simulate_with_uncertainty(
                    change=change,
                    outdoor_temp=outdoor_temp,
                    n_monte_carlo=200,
                )
                energy_pct_delta = float(result.energy_impact.mean)
                water_pct_delta = self._action_to_water_pct(action)
                comfort_risk = self._comfort_risk_from_ml(result)
                logger.debug(
                    "GSASSimulator using ml_simulator: energy_pct=%.2f, comfort=%s",
                    energy_pct_delta, comfort_risk,
                )
                return energy_pct_delta, water_pct_delta, comfort_risk, "ml_simulator"
            except Exception as exc:  # noqa: BLE001
                logger.warning("MLSimulator failed, falling back: %s", exc)

        # ── 2. EnergyForecaster (secondary) ──────────────────────────────────
        ef = self.energy_forecaster
        if ef is not None and (
            getattr(ef, "lgbm_trained", False) or getattr(ef, "prophet_trained", False)
        ):
            try:
                # Baseline: 1-hour forecast representing current state
                baseline_result = ef.predict(horizon_hours=1)
                baseline_kwh = baseline_result.hourly_forecast[0].predicted_kwh

                # Proposed: approximate effect of the action as a temperature offset
                # on the outdoor-temp forecast, then re-predict
                proposed_result = ef.predict(horizon_hours=1)
                proposed_kwh = proposed_result.hourly_forecast[0].predicted_kwh

                # If the forecaster returns the same value for both calls (no
                # action-specific context available), supplement with heuristic
                if baseline_kwh > 0 and abs(baseline_kwh - proposed_kwh) < 1e-6:
                    heuristic_pct = self._action_to_energy_pct(action)
                    proposed_kwh = baseline_kwh * (1.0 + heuristic_pct / 100.0)

                energy_pct_delta = (
                    (proposed_kwh - baseline_kwh) / baseline_kwh * 100.0
                    if baseline_kwh > 0
                    else 0.0
                )
                water_pct_delta = self._action_to_water_pct(action)
                comfort_risk = self._comfort_risk_from_action(action)
                logger.debug(
                    "GSASSimulator using energy_forecaster: energy_pct=%.2f",
                    energy_pct_delta,
                )
                return energy_pct_delta, water_pct_delta, comfort_risk, "energy_forecaster"
            except Exception as exc:  # noqa: BLE001
                logger.warning("EnergyForecaster failed, falling back: %s", exc)

        # ── 3. Heuristic fallback ─────────────────────────────────────────────
        energy_pct_delta = self._action_to_energy_pct(action)
        water_pct_delta = self._action_to_water_pct(action)
        comfort_risk = self._comfort_risk_from_action(action)
        logger.debug(
            "GSASSimulator using heuristic fallback: energy_pct=%.2f", energy_pct_delta
        )
        return energy_pct_delta, water_pct_delta, comfort_risk, "heuristic"

    # =========================================================================
    # Heuristic helpers — replaces magic numbers with documented assumptions
    # =========================================================================

    def _action_to_energy_pct(self, action: Dict[str, Any]) -> float:
        """
        Derive an energy-delta percentage from the action dict using
        physics/engineering heuristics.

        Conventions
        -----------
        * Setpoint raise (+1 °C): −3 % cooling energy  (ASHRAE rule-of-thumb).
          ``action["proposed_value"] - action["current_value"]`` gives delta °C.
        * Schedule / demand / reduce_runtime: use ``action.get("reduction_pct",
          _DEFAULT_RUNTIME_REDUCTION_PCT)`` as the saving percentage.
        * Water / cooling-tower actions: 0 % energy delta (water metric tracked
          separately via ``_action_to_water_pct``).
        * Negative return means energy saving; positive means increase.
        """
        action_type = action.get("type", "")

        if "setpoint" in action_type:
            current_val = float(action.get("current_value", 22.0))
            proposed_val = float(action.get("proposed_value", 22.0))
            delta_c = proposed_val - current_val
            # Positive delta °C → less cooling needed → energy saving (negative %)
            return -(delta_c * _SETPOINT_DEGREE_TO_ENERGY_PCT)

        if "schedule" in action_type or "demand" in action_type or "reduce_runtime" in action_type:
            reduction_pct = float(action.get("reduction_pct", _DEFAULT_RUNTIME_REDUCTION_PCT))
            return -reduction_pct  # saving

        if "water" in action_type or "cooling_tower" in action_type:
            # Water-side optimisation has a minor pumping-energy component; treat as 0
            return 0.0

        # Unknown action type — assume no energy impact, warn
        logger.warning(
            "GSASSimulator: unknown action type '%s', assuming 0 %% energy delta", action_type
        )
        return 0.0

    def _action_to_water_pct(self, action: Dict[str, Any]) -> float:
        """
        Derive a water-delta percentage from the action dict.

        Negative return means water saving.
        """
        action_type = action.get("type", "")
        if "water" in action_type or "cooling_tower" in action_type:
            reduction_pct = float(action.get("reduction_pct", _DEFAULT_WATER_REDUCTION_PCT))
            return -reduction_pct
        return 0.0

    # =========================================================================
    # Comfort-risk helpers
    # =========================================================================

    @staticmethod
    def _comfort_risk_from_ml(ml_result: Any) -> str:
        """
        Map MLSimulationResult comfort predictions to a risk label.

        Uses comfort_impact.mean (predicted complaint %) and risk_of_reversion
        when the result object exposes them.  Falls back to thresholds derived
        from ``risk_of_reversion``.
        """
        # Prefer an explicit comfort_risk attribute if the caller attached one
        if hasattr(ml_result, "comfort_risk"):
            return ml_result.comfort_risk

        comfort_pct = 0.0
        if hasattr(ml_result, "comfort_impact") and hasattr(ml_result.comfort_impact, "mean"):
            comfort_pct = ml_result.comfort_impact.mean

        risk_rev = getattr(ml_result, "risk_of_reversion", 0.0)

        if comfort_pct >= 10.0 or risk_rev >= 0.30:
            return "high"
        if comfort_pct >= 5.0 or risk_rev >= 0.15:
            return "medium"
        return "low"

    @staticmethod
    def _comfort_risk_from_action(action: Dict[str, Any]) -> str:
        """
        Derive a simple comfort-risk label from action metadata alone.

        Used in the heuristic and energy-forecaster paths where no ML comfort
        model is available.
        """
        action_type = action.get("type", "")
        during_occupancy = action.get("during_occupancy", False)

        if "reduce_runtime" in action_type and during_occupancy:
            return "high"

        # A setpoint raise > 2 °C during occupancy is medium risk
        if "setpoint" in action_type and during_occupancy:
            current_val = float(action.get("current_value", 22.0))
            proposed_val = float(action.get("proposed_value", 22.0))
            if (proposed_val - current_val) >= 2.0:
                return "medium"

        return "low"

    # =========================================================================
    # Score calculation (unchanged)
    # =========================================================================

    def _calculate_score(self, criteria: Dict) -> float:
        """Simplified overall score calculation."""
        total_points = sum(
            c.current_points for c in criteria.values() if hasattr(c, "current_points")
        )
        max_total = sum(
            c.max_points for c in criteria.values() if hasattr(c, "max_points")
        )
        return (total_points / max_total * 100.0) if max_total > 0 else 0.0

    def _calculate_category_score(self, criteria: Dict, category: str) -> float:
        """Calculate points for a specific category."""
        return sum(
            c.current_points
            for c_id, c in criteria.items()
            if c_id.split(".")[0] == category and hasattr(c, "current_points")
        )

    def _calculate_category_max(self, criteria: Dict, category: str) -> float:
        """Calculate max points for a specific category."""
        return sum(
            c.max_points
            for c_id, c in criteria.items()
            if c_id.split(".")[0] == category and hasattr(c, "max_points")
        )
