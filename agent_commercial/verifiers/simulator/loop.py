"""
Chilled Water Loop Hydraulic Model.

Relates: Q = m·Cp·ΔT, pump power via affinity law.
v1 thin model: single pump curve, no distribution losses. Patent claim 1(c)(iv) scope.

References:
  [1] ASHRAE Handbook 2020 — HVAC Systems & Equipment, Ch 22 "Centrifugal
      Pumps". Atlanta: ASHRAE, 2020. Affinity law derivation + pump curves.
  [2] Generic Q = m·Cp·ΔT energy balance (first law of thermodynamics).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

CP_WATER = 4186.0   # J/(kg·K)
RHO_WATER = 1000.0  # kg/m³


@dataclass
class LoopConfig:
    """CHW loop design parameters."""
    design_flow_lps: float = 120.0
    design_delta_t_c: float = 5.0
    design_head_kpa: float = 250.0
    pump_efficiency: float = 0.75
    n_pumps: int = 2
    design_pump_kw: float = 45.0  # Per pump
    version: str = "1.0.0"


@dataclass
class LoopState:
    """Current CHW loop operating conditions."""
    supply_temp_c: float
    return_temp_c: float
    flow_fraction: float  # Fraction of design flow (0-1)
    n_pumps_running: int = 2


@dataclass
class LoopResult:
    """CHW loop calculation outputs."""
    heat_removed_kw: float
    flow_lps: float
    flow_kg_s: float
    delta_t_c: float
    pumping_power_kw: float
    specific_power_kw_per_kw: float  # Pump kW per kW cooling


def predict_loop(state: LoopState, config: LoopConfig) -> LoopResult:
    """
    Calculate CHW loop performance.

    Q = m·Cp·ΔT
    Pump power: P = P_design × n_pumps × flow_fraction³ (affinity law)
    """
    delta_t = state.return_temp_c - state.supply_temp_c
    flow_frac = max(0.0, min(1.0, state.flow_fraction))

    flow_lps = config.design_flow_lps * flow_frac
    flow_kg_s = flow_lps * RHO_WATER / 1000.0

    heat_removed_kw = flow_kg_s * CP_WATER * max(delta_t, 0.0) / 1000.0

    pump_kw = config.design_pump_kw * state.n_pumps_running * (flow_frac ** 3)

    specific = pump_kw / max(heat_removed_kw, 0.1)

    return LoopResult(
        heat_removed_kw=heat_removed_kw,
        flow_lps=flow_lps,
        flow_kg_s=flow_kg_s,
        delta_t_c=delta_t,
        pumping_power_kw=pump_kw,
        specific_power_kw_per_kw=specific,
    )


def required_flow_for_load(
    cooling_load_kw: float,
    delta_t_c: float,
    config: LoopConfig,
) -> float:
    """
    Calculate required CHW flow fraction for given load and delta-T.

    flow_kg_s = Q / (Cp × ΔT)
    Returns flow as fraction of design flow.
    """
    if delta_t_c <= 0.0:
        return 1.0
    flow_kg_s = (cooling_load_kw * 1000.0) / (CP_WATER * delta_t_c)
    flow_lps = flow_kg_s * 1000.0 / RHO_WATER
    return flow_lps / max(config.design_flow_lps, 0.1)


def validate_flow_balance(
    total_load_kw: float,
    supply_temp_c: float,
    return_temp_c: float,
    flow_fraction: float,
    config: LoopConfig,
    tolerance: float = 0.20,
) -> Tuple[bool, float, float]:
    """
    Validate flow-temperature-load consistency (Q triangle).

    Checks: Q_from_flow_and_temps vs Q_stated within tolerance.
    Returns: (is_valid, q_from_flow_kw, q_stated_kw)
    """
    delta_t = return_temp_c - supply_temp_c
    flow_lps = config.design_flow_lps * max(0.0, min(1.0, flow_fraction))
    flow_kg_s = flow_lps * RHO_WATER / 1000.0

    q_from_flow = flow_kg_s * CP_WATER * max(delta_t, 0.0) / 1000.0
    q_stated = total_load_kw

    if q_stated <= 0.0:
        return True, q_from_flow, q_stated

    deviation = abs(q_from_flow - q_stated) / max(q_stated, 0.1)
    return deviation <= tolerance, q_from_flow, q_stated
