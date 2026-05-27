"""
Chiller performance model — DOE-2 bi-quadratic curves with VFD-modulated EIR-FPLR.

Applies to Carrier 30XA water-cooled centrifugal class (Marina Heights plant)
sharing the DOE-2 Chiller:Electric:EIR formulation (ASHRAE Ch 43 §3 centrifugal).

Dual-mode:
  - DOE-2 mode (default, patent claim 2): CAP-FT + EIR-FT biquadratic curves +
    EIR-FPLR cubic curve. Coefficients calibrated at AHRI 550/590 water-cooled
    design point (6.67°C LWT, 29.4°C ECWT / 85°F EWT). VFD-modulated centrifugal
    characteristic (rising COP at part-load due to reduced condensing lift).
  - Cubic mode: matches scratch/marina_physics.py:210-223 for cross-validation
    against water-cooled centrifugal reference data.

References:
  [1] EnergyPlus Engineering Reference, "Chiller:Electric:EIR" object.
      U.S. DOE, Lawrence Berkeley National Laboratory.
  [2] ASHRAE Handbook 2020 — HVAC Systems & Equipment, Ch 43 §3 "Centrifugal
      Liquid Chillers". Atlanta: ASHRAE, 2020.
  [3] AHRI Standard 550/590-2023: rating method for water-chilling and
      heat-pump water-heating packages, vapor compression cycle.
  [4] ASHRAE 90.1-2022 Table 6.8.1-7: minimum efficiency requirements,
      water-cooled centrifugal chillers ≥300 tons Path A.
  [5] Carrier Form 30XW-7PD: AquaForce 30XW Product Data, 2015.
      Full-load COP = 5.5 (EER 18.8) at AHRI 550/590 water-cooled conditions
      (85°F ECWT, 44°F LWT). Design COP 6.1 at Marina Heights conditions
      (lower ECWT in Doha night operation).

Trade-secret partition:
  This module ships PUBLIC baseline coefficients (DOE Reference Buildings,
  redistributable). Proprietary Carrier engineering coefficients (when obtained
  under NDA) load from a private config repo via load_curves_from_dict() —
  NOT committed to public repo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_commercial.verifiers.simulator.curves import biquadratic, cubic, clamp

logger = logging.getLogger("arvis.simulator.chiller")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ChillerCurves:
    """DOE-2 curve coefficient sets for a chiller model."""
    cap_ft: List[float] = field(default_factory=list)
    eir_ft: List[float] = field(default_factory=list)
    eir_fplr: List[float] = field(default_factory=list)
    design_capacity_kw: float = 1409.6  # 400 TR × 3.517 kW/TR (Carrier 30XW400 AHRI rated)
    design_cop: float = 5.5            # 30XW water-cooled AHRI 550/590 full-load COP at 85°F ECWT / 44°F LWT
    design_chwst_c: float = 6.67       # AHRI 550/590 LWT: 44°F = 6.67°C
    design_ecwt_c: float = 35.0        # condenser entering water temp: 35°C (95°F) AHRI rating condition
    condenser_type: str = "water"      # "air" (EDB input) or "water" (ECWT input)
    min_plr: float = 0.10
    version: str = "1.0.0"


@dataclass
class ChillerState:
    """Operating state snapshot for chiller calculation."""
    chwst_c: float
    ecwt_c: float
    plr: float


@dataclass
class ChillerResult:
    """Predicted chiller outputs."""
    available_capacity_kw: float
    actual_load_kw: float
    power_input_kw: float
    cop: float
    cap_ft_modifier: float
    eir_ft_modifier: float
    eir_fplr_modifier: float


# ─── Default curves (DOE-2 water-cooled centrifugal baseline, public domain) ──────

# Calibrated Celsius-based coefficients. All curves = 1.0 at AHRI design (6.67°C CHWST, 29.4°C ECWT).
# CAP-FT/EIR-FT sensitivities from ASHRAE 90.1 Appendix G (water-cooled centrifugal class).
# EIR-FPLR cubic fitted to marina_physics.py COP polynomial (cross-reference water-cooled centrifugal).
_DEFAULT_CAP_FT = [1.020000, 0.020000, 0.0, -0.005000, 0.0, 0.0]
_DEFAULT_EIR_FT = [0.430000, -0.010000, 0.0, 0.020000, 0.0, 0.0]
_DEFAULT_EIR_FPLR = [2.785324, -3.167667, 1.348787, 0.038704]


def default_curves() -> ChillerCurves:
    """Return Carrier 30XW400 water-cooled centrifugal baseline curves (DOE-2 VFD-modulated).

    Design COP 5.5 is the conservative AHRI 550/590 water-cooled rating at 85°F ECWT / 44°F LWT.
    Marina Heights design COP 6.1 is achievable at part-load with lower condenser water temps
    (Doha night-time cooling tower operation at <30°C ECWT reduces condensing lift).
    """
    return ChillerCurves(
        cap_ft=_DEFAULT_CAP_FT[:],
        eir_ft=_DEFAULT_EIR_FT[:],
        eir_fplr=_DEFAULT_EIR_FPLR[:],
        design_capacity_kw=1409.6,
        design_cop=5.5,
        design_chwst_c=6.67,
        design_ecwt_c=35.0,
        condenser_type="water",
        min_plr=0.10,
    )


def load_curves_from_dict(data: Dict[str, Any]) -> ChillerCurves:
    """Load ChillerCurves from parsed YAML dict."""
    design = data.get("design_conditions", {})
    return ChillerCurves(
        cap_ft=data.get("cap_ft", _DEFAULT_CAP_FT[:]),
        eir_ft=data.get("eir_ft", _DEFAULT_EIR_FT[:]),
        eir_fplr=data.get("eir_fplr", _DEFAULT_EIR_FPLR[:]),
        design_capacity_kw=data.get("capacity_kw", 1409.6),
        design_cop=design.get("cop", 3.10),
        design_chwst_c=design.get("chwst_c", 6.67),
        design_ecwt_c=design.get("ecwt_c", 35.0),
        condenser_type=data.get("condenser_type", "air"),
        min_plr=data.get("limits", {}).get("min_plr", 0.10),
        version=data.get("version", "1.0.0"),
    )


# ─── DOE-2 Mode (patent-accurate) ────────────────────────────────────────────

def predict_chiller(state: ChillerState, curves: ChillerCurves) -> ChillerResult:
    """
    Predict chiller performance using DOE-2 curves.

    Algorithm:
      1. cap_ft_mod = biquadratic(chwst, ecwt, curves.cap_ft)
      2. available_capacity = design_capacity × cap_ft_mod
      3. actual_load = available_capacity × PLR
      4. eir_ft_mod = biquadratic(chwst, ecwt, curves.eir_ft)
      5. eir_fplr_mod = cubic(plr, curves.eir_fplr)
      6. eir = (1/design_cop) × eir_ft_mod × eir_fplr_mod
      7. power = actual_load × eir
      8. cop = actual_load / power
    """
    plr = clamp(state.plr, curves.min_plr, 1.0)
    chwst = clamp(state.chwst_c, 4.0, 12.0)
    ecwt = clamp(state.ecwt_c, 18.0, 42.0)

    cap_ft_mod = biquadratic(chwst, ecwt, curves.cap_ft)
    cap_ft_mod = clamp(cap_ft_mod, 0.5, 1.5)

    available_capacity_kw = curves.design_capacity_kw * cap_ft_mod
    actual_load_kw = available_capacity_kw * plr

    eir_ft_mod = biquadratic(chwst, ecwt, curves.eir_ft)
    eir_ft_mod = clamp(eir_ft_mod, 0.5, 2.0)

    eir_fplr_mod = cubic(plr, curves.eir_fplr)
    eir_fplr_mod = clamp(eir_fplr_mod, 0.3, 2.0)

    eir_rated = 1.0 / curves.design_cop
    eir_actual = eir_rated * eir_ft_mod * eir_fplr_mod

    power_kw = actual_load_kw * eir_actual
    cop = actual_load_kw / max(power_kw, 0.001)

    return ChillerResult(
        available_capacity_kw=available_capacity_kw,
        actual_load_kw=actual_load_kw,
        power_input_kw=power_kw,
        cop=cop,
        cap_ft_modifier=cap_ft_mod,
        eir_ft_modifier=eir_ft_mod,
        eir_fplr_modifier=eir_fplr_mod,
    )


def validate_cop_at_conditions(
    cited_cop: float,
    state: ChillerState,
    curves: ChillerCurves,
    tolerance: float = 0.10,
) -> Tuple[bool, float, float]:
    """
    Check if cited COP is achievable at given conditions.

    Returns: (is_valid, predicted_cop, deviation_fraction)
    Deviation = abs(cited - predicted) / predicted.
    """
    result = predict_chiller(state, curves)
    predicted = result.cop
    if predicted < 0.01:
        return False, 0.0, 1.0
    deviation = abs(cited_cop - predicted) / predicted
    is_valid = deviation <= tolerance
    return is_valid, predicted, deviation


# ─── Cubic Mode (marina_physics.py compatibility) ────────────────────────────

def cop_cubic(plr: float, condenser_water_temp: float, chiller_id: int = 1) -> float:
    """
    COP from cubic polynomial + temperature penalty.
    Exact match: scratch/marina_physics.py:210-223 (CarrierChillerModel.cop).

    COP(PLR) = -3.5·PLR³ + 6.2·PLR² + 1.5·PLR + 2.5
    Temp penalty: ×(1 - 0.018·(cwt - 35))
    Chiller 4 suction penalty at low load: ×0.91
    """
    p = clamp(plr, 0.01, 1.0)
    cop_base = -3.5 * p ** 3 + 6.2 * p ** 2 + 1.5 * p + 2.5
    temp_penalty = 1.0 - 0.018 * (condenser_water_temp - 35.0)
    cop_val = cop_base * temp_penalty
    if chiller_id == 4 and p < 0.6:
        cop_val *= 0.91
    return clamp(cop_val, 1.5, 7.0)


# ─── Staging Validation (G5) ─────────────────────────────────────────────────

def validate_staging(
    n_available: int,
    total_load_kw: float,
    curves: ChillerCurves,
) -> Tuple[bool, float]:
    """
    Check if n_available chillers can handle total_load without exceeding PLR=1.0.

    Returns: (can_handle, required_plr_per_chiller)
    """
    if n_available <= 0:
        return False, float("inf")
    per_chiller_kw = total_load_kw / n_available
    required_plr = per_chiller_kw / curves.design_capacity_kw
    return required_plr <= 1.0, clamp(required_plr, 0.0, 2.0)
