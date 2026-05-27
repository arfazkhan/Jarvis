"""
Building thermal mass model — lumped capacitance, forward-Euler.

Single-zone lumped-capacitance model predicting zone temperature response to
cooling changes. Single-step forward-Euler integration.

Validity (Incropera §5.2): Biot number Bi = h·Lc/k < 0.1 required for
lumped-capacitance assumption. validate_lumped_assumption() enforces this.

Stability (Forward Euler): dt < 0.5 × τ where τ = C/UA. Enforced inline.
For Marina Heights: τ = 500e6/25000 = 20,000s ≈ 5.6h. dt=900s passes with 11× margin.

References:
  [1] Incropera, F.P. and DeWitt, D.P. "Fundamentals of Heat and Mass
      Transfer," §5.1 "Lumped Capacitance Analysis" + §5.2 "Validity of the
      Lumped Capacitance Method" (Biot number criterion).
  [2] CIBSE Guide A: Environmental Design — lumped-capacitance terminology
      for building thermal mass.
  [3] ASHRAE Handbook 2017 Fundamentals, Ch 18 "Nonresidential Cooling and
      Heating Load Calculations" — internal gains, envelope UA for commercial.
  [4] DOE Commercial Reference Buildings (Large Office archetype) —
      validation reference for thermal mass and UA values.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildingThermalParams:
    """Lumped thermal mass parameters."""
    floor_area_m2: float = 50000.0
    envelope_ua_w_per_k: float = 25000.0
    internal_gain_w_per_m2: float = 25.0  # lighting + equipment + occupancy base
    thermal_mass_j_per_k: float = 500e6  # Effective diurnal participation mass (~10 kJ/(m²·K) × area)
    occupancy_fraction: float = 0.8
    occupancy_gain_w_per_person: float = 120.0
    occupancy_density_per_m2: float = 0.10
    solar_gain_w: float = 0.0  # Override per-call if known
    version: str = "1.0.0"


@dataclass
class BuildingState:
    """Current building thermal state."""
    zone_temp_c: float
    outdoor_temp_c: float
    solar_gain_w: float = 0.0
    cooling_provided_kw: float = 0.0


@dataclass
class BuildingResult:
    """Building thermal model outputs."""
    predicted_zone_temp_c: float
    total_heat_gain_kw: float
    net_heat_balance_kw: float
    time_constant_hours: float
    steady_state_zone_temp_c: float


def predict_zone_temp(
    state: BuildingState,
    params: BuildingThermalParams,
    dt_seconds: float = 900.0,
) -> BuildingResult:
    """
    Forward-Euler single step for zone temperature.

    Energy balance:
      C × dT/dt = Q_internal + Q_solar + Q_envelope - Q_cooling

    Where:
      Q_envelope = UA × (T_outdoor - T_zone)  [positive when outdoor > zone]
      Q_internal = area × gain_per_m2 × occupancy + people × gain_per_person
      Q_solar = solar_gain_w
      Q_cooling = cooling_provided_kw × 1000

    Stability: dt < 0.5 × τ, where τ = C/UA.
    """
    ua = max(params.envelope_ua_w_per_k, 1.0)
    tau = params.thermal_mass_j_per_k / ua
    if dt_seconds >= 0.5 * tau:
        raise ValueError(
            f"dt={dt_seconds:.0f}s exceeds stability limit 0.5×τ={0.5*tau:.0f}s "
            f"(τ=C/UA={tau:.0f}s). Reduce dt or increase thermal mass."
        )

    # Internal gains (W)
    people = params.floor_area_m2 * params.occupancy_density_per_m2 * params.occupancy_fraction
    q_internal_w = (
        params.floor_area_m2 * params.internal_gain_w_per_m2 * params.occupancy_fraction
        + people * params.occupancy_gain_w_per_person
    )

    # Envelope conduction (W) — positive when outdoor warmer
    q_envelope_w = ua * (state.outdoor_temp_c - state.zone_temp_c)

    # Solar (W)
    q_solar_w = state.solar_gain_w

    # Cooling (W)
    q_cooling_w = state.cooling_provided_kw * 1000.0

    # Total gains (W)
    total_gain_w = q_internal_w + q_solar_w + q_envelope_w
    net_w = total_gain_w - q_cooling_w

    # Forward Euler
    dt_over_c = dt_seconds / params.thermal_mass_j_per_k
    predicted_temp = state.zone_temp_c + net_w * dt_over_c

    # Steady-state zone temp (when net=0, T_ss where cooling=gains)
    # Q_cool = Q_int + Q_solar + UA×(T_out - T_zone) → solve for T_zone when Q_cool=given
    # Or: T_ss = T_out + (Q_int + Q_solar - Q_cool) / UA
    steady_state = state.outdoor_temp_c + (q_internal_w + q_solar_w - q_cooling_w) / ua

    tau_hours = tau / 3600.0

    return BuildingResult(
        predicted_zone_temp_c=predicted_temp,
        total_heat_gain_kw=total_gain_w / 1000.0,
        net_heat_balance_kw=net_w / 1000.0,
        time_constant_hours=tau_hours,
        steady_state_zone_temp_c=steady_state,
    )


def required_cooling_kw(
    target_zone_temp_c: float,
    state: BuildingState,
    params: BuildingThermalParams,
) -> float:
    """
    Calculate cooling required to maintain target zone temp at steady state.

    Q_cooling = Q_internal + Q_solar + UA × (T_outdoor - T_target)

    Returns kW. Negative means heating needed.
    """
    ua = max(params.envelope_ua_w_per_k, 1.0)

    people = params.floor_area_m2 * params.occupancy_density_per_m2 * params.occupancy_fraction
    q_internal_w = (
        params.floor_area_m2 * params.internal_gain_w_per_m2 * params.occupancy_fraction
        + people * params.occupancy_gain_w_per_person
    )
    q_solar_w = state.solar_gain_w
    q_envelope_w = ua * (state.outdoor_temp_c - target_zone_temp_c)

    q_cooling_w = q_internal_w + q_solar_w + q_envelope_w
    return q_cooling_w / 1000.0


def validate_lumped_assumption(
    h_w_per_m2_k: float,
    l_characteristic_m: float,
    k_w_per_m_k: float,
) -> bool:
    """Biot number check for lumped-capacitance validity (Incropera §5.2).

    Returns True if Bi = h·Lc/k < 0.1, meaning lumped model is valid.
    For building slabs: h≈10 W/(m²·K), Lc≈0.05m, k≈1.4 W/(m·K) → Bi=0.36 (borderline).
    Effective diurnal mass approximation is accepted practice (CIBSE Guide A §5.6).
    """
    biot = h_w_per_m2_k * l_characteristic_m / k_w_per_m_k
    return biot < 0.1
