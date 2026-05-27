"""
AHU steady-state thermal balance model.

Sequence: mixing box → cooling coil → supply fan → final SAT.
All steady-state, single evaluation per advisory check. Quasi-steady-state
operation; <50ms per advisory check (patent claim 7).

Fan affinity law exponent 2.7 (empirical, not theoretical 3.0):
  Theoretical cube law applies to pure aerodynamic work only.
  Real VFD-driven fans incur additional losses from inverter, motor, and belt.
  Per ASHRAE Ch 21 §5 caveat: "the fan laws only apply to fans and must not
  be used to calculate performance of other system components, such as drive
  belts, motors, or variable-frequency drives." Empirical exponent 2.6-2.8
  is industry standard; 2.7 is the midrange default used here.

References:
  [1] ASHRAE Handbook 2020 — HVAC Systems & Equipment, Ch 21 "Fans",
      §5 "Fan Laws" Table 2, p. 21.7. Atlanta: ASHRAE, 2020.
  [2] ASHRAE Handbook 2020 HVAC SE, Ch 23 "Air-Cooling and Dehumidifying
      Coils" (via cooling_coil.py).
  [3] AMCA Publication 203: Field performance measurement of fan systems.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agent_commercial.verifiers.simulator.cooling_coil import (
    CoilGeometry,
    CoilResult,
    CoilState,
    CP_AIR,
    cfm_to_kg_s,
    predict_coil,
)


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class AHUConfig:
    """AHU design parameters."""
    design_cfm: float = 20000.0
    design_fan_kw: float = 15.0
    fan_exponent: float = 2.7  # empirical VFD exponent; ASHRAE 2020 HVAC SE Ch 21 §5 Table 2
    min_oa_fraction: float = 0.15
    coil_geometry: Optional[CoilGeometry] = None
    version: str = "1.0.0"

    def __post_init__(self):
        if self.coil_geometry is None:
            self.coil_geometry = CoilGeometry()


@dataclass
class AHUState:
    """Current AHU operating conditions."""
    outdoor_air_temp_c: float
    return_air_temp_c: float
    oa_damper_fraction: float   # 0-1 (0=all return, 1=all OA)
    fan_speed_fraction: float   # 0-1
    chw_supply_temp_c: float
    chw_flow_kg_s: float


@dataclass
class AHUResult:
    """AHU thermal balance outputs."""
    mixed_air_temp_c: float
    supply_air_temp_c: float
    coil_load_kw: float
    fan_power_kw: float
    fan_heat_rise_c: float
    air_flow_kg_s: float
    coil_result: Optional[CoilResult] = None


# ─── Component Functions ──────────────────────────────────────────────────────

def mixing_box(oat_c: float, rat_c: float, oa_fraction: float) -> float:
    """Mixed air temperature: MAT = OA×OAT + (1-OA)×RAT."""
    oa = max(0.0, min(1.0, oa_fraction))
    return oa * oat_c + (1.0 - oa) * rat_c


def fan_power(speed_fraction: float, design_kw: float, exponent: float = 2.7) -> float:
    """Fan affinity law: P = P_design × speed^exponent."""
    spd = max(0.0, min(1.0, speed_fraction))
    return design_kw * (spd ** exponent)


def fan_heat_rise(fan_power_kw: float, air_flow_kg_s: float) -> float:
    """Temperature rise through fan: ΔT = P / (m·Cp). Returns °C."""
    if air_flow_kg_s <= 0.0:
        return 0.0
    return (fan_power_kw * 1000.0) / (air_flow_kg_s * CP_AIR)


# ─── Main Prediction ─────────────────────────────────────────────────────────

def predict_ahu(state: AHUState, config: AHUConfig) -> AHUResult:
    """
    Full AHU steady-state thermal balance.

    1. Mixed air temp from mixing box
    2. Air mass flow from fan speed × design CFM
    3. Cooling coil (NTU-effectiveness)
    4. Fan power and heat rise
    5. Final SAT = coil leaving temp + fan heat rise
    """
    mat = mixing_box(state.outdoor_air_temp_c, state.return_air_temp_c, state.oa_damper_fraction)

    air_flow_kg_s = cfm_to_kg_s(config.design_cfm * max(0.1, state.fan_speed_fraction))

    coil_state = CoilState(
        air_entering_temp_c=mat,
        air_flow_kg_s=air_flow_kg_s,
        water_entering_temp_c=state.chw_supply_temp_c,
        water_flow_kg_s=state.chw_flow_kg_s,
    )
    coil_result = predict_coil(coil_state, config.coil_geometry)

    fp = fan_power(state.fan_speed_fraction, config.design_fan_kw, config.fan_exponent)
    fhr = fan_heat_rise(fp, air_flow_kg_s)

    sat = coil_result.air_leaving_temp_c + fhr

    return AHUResult(
        mixed_air_temp_c=mat,
        supply_air_temp_c=sat,
        coil_load_kw=coil_result.heat_transfer_kw,
        fan_power_kw=fp,
        fan_heat_rise_c=fhr,
        air_flow_kg_s=air_flow_kg_s,
        coil_result=coil_result,
    )
