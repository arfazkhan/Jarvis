"""
Cooling coil heat transfer model — NTU-effectiveness method.

Cross-flow, both fluids unmixed (standard AHU cooling coil configuration).

v1 scope: SENSIBLE heat transfer only (Cr ≈ 0 cross-flow unmixed).
v2 plan: latent partition via apparatus dew-point (ADP) + bypass factor (BF)
         per ASHRAE Ch 23 §7. Qatar humidity 60-81% makes latent dominant
         in Marina S1-P7 scenarios; v2 required for full hygrothermal accuracy.

References:
  [1] ASHRAE Handbook 2020 — HVAC Systems & Equipment, Ch 23
      "Air-Cooling and Dehumidifying Coils", §6 Sensible Performance,
      §7 Performance of Dehumidifying Coils, pp. 23.7-23.9. Atlanta: ASHRAE, 2020.
      Equations (1a, 1b, 5c) sensible coil; (7c, 7d, 7e) NTU-effectiveness.
  [2] AHRI Standard 410: rating thermal performance of dehumidifying coils.
  [3] Incropera, F.P. and DeWitt, D.P. "Fundamentals of Heat and Mass
      Transfer," Table 11.3 (cross-flow effectiveness, both fluids unmixed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ─── Thermodynamic Constants ──────────────────────────────────────────────────

CP_AIR = 1005.0      # J/(kg·K) — specific heat of dry air at ~25°C
CP_WATER = 4186.0    # J/(kg·K) — specific heat of water
RHO_AIR = 1.225      # kg/m³ — air density at sea level, 15°C
RHO_WATER = 1000.0   # kg/m³ — water density


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class CoilGeometry:
    """Physical parameters of a cooling coil."""
    rows: int = 6
    tubes_per_row: int = 40
    tube_od_m: float = 0.016
    fin_pitch_per_m: float = 394
    face_area_m2: float = 3.5
    ua_design_w_per_k: float = 85000.0  # ASHRAE 2020 HVAC SE Ch 23 (6-row, 3.5m² face, 10 FPI)
    version: str = "1.0.0"


@dataclass
class CoilState:
    """Operating conditions for cooling coil calculation."""
    air_entering_temp_c: float
    air_flow_kg_s: float
    water_entering_temp_c: float
    water_flow_kg_s: float


@dataclass
class CoilResult:
    """Cooling coil calculation outputs."""
    air_leaving_temp_c: float
    water_leaving_temp_c: float
    heat_transfer_kw: float
    effectiveness: float
    ntu: float
    latent_included: bool = False  # v1: sensible only


# ─── Core Functions ───────────────────────────────────────────────────────────

def effectiveness_crossflow_unmixed(ntu: float, c_ratio: float) -> float:
    """
    NTU-effectiveness for cross-flow, both fluids unmixed.

    ε = 1 - exp((NTU^0.22 / Cr) × (exp(-Cr × NTU^0.78) - 1))

    Special cases:
      - Cr = 0 → ε = 1 - exp(-NTU) (one fluid has infinite capacity)
      - NTU = 0 → ε = 0

    Reference: Incropera & DeWitt, Table 11.3.
    """
    if ntu <= 0.0:
        return 0.0
    if c_ratio <= 1e-6:
        return 1.0 - math.exp(-ntu)

    exponent_inner = -c_ratio * (ntu ** 0.78)
    term = (ntu ** 0.22) / c_ratio * (math.exp(exponent_inner) - 1.0)
    eps = 1.0 - math.exp(term)
    return max(0.0, min(1.0, eps))


def predict_coil(state: CoilState, geometry: CoilGeometry) -> CoilResult:
    """
    Predict cooling coil performance using NTU-effectiveness method.

    Algorithm:
      1. C_air = m_air × Cp_air
      2. C_water = m_water × Cp_water
      3. C_min, C_max = sorted
      4. Cr = C_min / C_max
      5. NTU = UA / C_min
      6. ε = effectiveness_crossflow_unmixed(NTU, Cr)
      7. Q_max = C_min × (T_air_in - T_water_in)
      8. Q_actual = ε × Q_max
      9. T_air_out = T_air_in - Q / C_air
     10. T_water_out = T_water_in + Q / C_water

    Performance: ~0.05ms (arithmetic only).
    """
    c_air = state.air_flow_kg_s * CP_AIR
    c_water = state.water_flow_kg_s * CP_WATER

    if c_air <= 0.0 or c_water <= 0.0:
        return CoilResult(
            air_leaving_temp_c=state.air_entering_temp_c,
            water_leaving_temp_c=state.water_entering_temp_c,
            heat_transfer_kw=0.0,
            effectiveness=0.0,
            ntu=0.0,
        )

    c_min = min(c_air, c_water)
    c_max = max(c_air, c_water)
    c_ratio = c_min / c_max

    ntu = geometry.ua_design_w_per_k / c_min
    eps = effectiveness_crossflow_unmixed(ntu, c_ratio)

    q_max = c_min * (state.air_entering_temp_c - state.water_entering_temp_c)
    q_actual = eps * q_max  # Watts

    air_leaving = state.air_entering_temp_c - q_actual / c_air
    water_leaving = state.water_entering_temp_c + q_actual / c_water

    return CoilResult(
        air_leaving_temp_c=air_leaving,
        water_leaving_temp_c=water_leaving,
        heat_transfer_kw=q_actual / 1000.0,
        effectiveness=eps,
        ntu=ntu,
    )


# ─── Unit Conversion Helpers ──────────────────────────────────────────────────

def cfm_to_kg_s(cfm: float, rho: float = RHO_AIR) -> float:
    """Convert volumetric airflow (CFM) to mass flow (kg/s). 1 CFM = 0.000472 m³/s."""
    return cfm * 0.000472 * rho


def lps_to_kg_s(lps: float, rho: float = RHO_WATER) -> float:
    """Convert volumetric water flow (L/s) to mass flow (kg/s)."""
    return lps * rho / 1000.0
