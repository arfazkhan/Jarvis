"""
Avoidable cost and priority scores for confirmed faults.

Energy is only quantified from the building's own measurements over the
confirmed fault samples — e.g. airflow × ΔT across a coil that should be off,
or an equipment's own kW while it ran without need. When a needed point or
site figure (tariff, plant COP) is missing the result says exactly that; it
never falls back to an assumed airflow or rate.

Physics constants used (not site assumptions): standard air density
1.2 kg/m³ and cp 1.006 kJ/kg·K.

Scores (0–10, Clockworks-style) are derived transparently:
  energy  — log scale of projected annual avoidable cost (100 → 0, 10k → 5, 1M → 10)
  comfort — share of running time the comfort-affecting fault was present
  health  — share of running time an equipment-wear / hardware fault was present
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from agent_commercial.fdd.timeseries import sample_durations
from agent_commercial.semantics import PointRole as R

AIR_DENSITY = 1.2      # kg/m³
AIR_CP = 1.006         # kJ/(kg·K)


@dataclass
class SiteEconomics:
    tariff_per_kwh: Optional[float] = None     # electricity, currency per kWh
    plant_cop: Optional[float] = None          # cooling kW delivered per electric kW
    heating_cop: Optional[float] = None        # 1.0 for electric-resistance reheat
    currency: str = "QAR"

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "SiteEconomics":
        d = d or {}
        f = lambda k: float(d[k]) if d.get(k) not in (None, "") else None  # noqa: E731
        return cls(tariff_per_kwh=f("tariff_per_kwh"), plant_cop=f("plant_cop"),
                   heating_cop=f("heating_cop"), currency=str(d.get("currency", "QAR")))


def _col(d: pd.DataFrame, role) -> Optional[pd.Series]:
    c = role.value if isinstance(role, R) else role
    if c in d.columns and d[c].notna().any():
        return pd.to_numeric(d[c], errors="coerce")
    return None


def _hours(mask: pd.Series, poll: float) -> pd.Series:
    dur = sample_durations(mask.index, poll)
    return (dur if dur is not None else pd.Series(poll, index=mask.index)) / 3600.0


def _not_quantifiable(method: str, reason: str) -> Dict[str, Any]:
    return {"status": "not_quantifiable", "method": method, "reason": reason}


def _finish(method: str, basis: str, confirmed: pd.Series, poll: float, econ: SiteEconomics,
            window_h: float, *, thermal_kw: Optional[pd.Series] = None,
            electric_kw: Optional[pd.Series] = None, thermal_is: str = "cooling",
            inputs: Dict[str, str], assumptions: list) -> Dict[str, Any]:
    h = _hours(confirmed, poll)
    out: Dict[str, Any] = {"status": "quantified", "method": method, "basis": basis,
                           "inputs": inputs, "assumptions": list(assumptions),
                           "fault_hours": round(float(h[confirmed].sum()), 2)}
    elec_kwh = None
    if thermal_kw is not None:
        thermal_kwh = float((thermal_kw.clip(lower=0).fillna(0) * h)[confirmed].sum())
        out[f"{thermal_is}_kwh_thermal"] = round(thermal_kwh, 1)
        cop = econ.plant_cop if thermal_is == "cooling" else econ.heating_cop
        if cop:
            elec_kwh = thermal_kwh / cop
            out["assumptions"].append(f"{thermal_is} COP {cop:g} (site)")
        else:
            out["electric_kwh_note"] = f"{'plant' if thermal_is == 'cooling' else 'heating'}_cop not configured"
    if electric_kw is not None:
        elec_kwh = float((electric_kw.clip(lower=0).fillna(0) * h)[confirmed].sum())
    if elec_kwh is not None:
        out["electric_kwh"] = round(elec_kwh, 1)
        if econ.tariff_per_kwh:
            cost = elec_kwh * econ.tariff_per_kwh
            out["cost"] = round(cost, 2)
            out["currency"] = econ.currency
            if window_h >= 24:
                out["projected_annual_cost"] = round(cost * 8760.0 / window_h, 0)
                out["projection_note"] = ("if the fault continues at the rate observed over the "
                                          f"last {window_h:.0f} h")
        else:
            out["cost_note"] = "electricity tariff not configured"
    return out


def _airflow(d) -> Optional[pd.Series]:
    return _col(d, R.SUPPLY_AIRFLOW)


def chw_valve_leak(d, confirmed, poll, econ, window_h):
    flow = _airflow(d)
    if flow is None:
        return _not_quantifiable("chw_valve_leak", "needs a supply-airflow point on this unit")
    ccet, cclt = _col(d, R.COOLING_COIL_ENTERING_TEMP), _col(d, R.COOLING_COIL_LEAVING_TEMP)
    if ccet is not None and cclt is not None:
        dt, basis, used = ccet - cclt, "airflow × ΔT across the closed cooling coil", {
            "dt": "cooling-coil-entering-temp − cooling-coil-leaving-temp"}
    else:
        mat, sat = _col(d, R.MIXED_AIR_TEMP), _col(d, R.SUPPLY_AIR_TEMP)
        if mat is None or sat is None:
            return _not_quantifiable("chw_valve_leak", "needs coil entering/leaving or mixed/supply air temps")
        dt, basis, used = mat - sat, "airflow × (mixed − supply air) with the cooling valve closed", {
            "dt": "mixed-air-temp − supply-air-temp"}
    q = AIR_DENSITY * flow * AIR_CP * dt
    return _finish("chw_valve_leak", basis, confirmed, poll, econ, window_h, thermal_kw=q,
                   inputs={"airflow": R.SUPPLY_AIRFLOW.value, **used},
                   assumptions=["standard air density and specific heat"])


def excess_outdoor_air(d, confirmed, poll, econ, window_h):
    flow, mat, rat = _airflow(d), _col(d, R.MIXED_AIR_TEMP), _col(d, R.RETURN_AIR_TEMP)
    if flow is None or mat is None or rat is None:
        return _not_quantifiable("excess_outdoor_air", "needs supply airflow, mixed-air and return-air temps")
    q = AIR_DENSITY * flow * AIR_CP * (mat - rat)
    return _finish("excess_outdoor_air", "extra cooling load of hot outdoor air: airflow × (mixed − return)",
                   confirmed, poll, econ, window_h, thermal_kw=q,
                   inputs={"airflow": R.SUPPLY_AIRFLOW.value, "dt": "mixed-air-temp − return-air-temp"},
                   assumptions=["standard air density and specific heat"])


def simultaneous_heat_cool(d, confirmed, poll, econ, window_h):
    flow, hcet, hclt = _airflow(d), _col(d, R.HEATING_COIL_ENTERING_TEMP), _col(d, R.HEATING_COIL_LEAVING_TEMP)
    if flow is not None and hcet is not None and hclt is not None:
        q, used = AIR_DENSITY * flow * AIR_CP * (hclt - hcet), {"airflow": R.SUPPLY_AIRFLOW.value,
                                                                "dt": "heating coil leaving − entering"}
    else:
        tflow, dat = _col(d, R.TERMINAL_AIRFLOW), _col(d, R.TERMINAL_DISCHARGE_TEMP)
        inlet = _col(d, R.TERMINAL_INLET_TEMP)
        if inlet is None:
            inlet = _col(d, "ctx:parent-supply-air-temp")
        if tflow is None or dat is None or inlet is None:
            return _not_quantifiable("simultaneous_heat_cool",
                                     "needs airflow and the temperature rise across the heating coil")
        q, used = AIR_DENSITY * tflow * AIR_CP * (dat - inlet), {"airflow": R.TERMINAL_AIRFLOW.value,
                                                                 "dt": "box discharge − inlet air"}
    return _finish("simultaneous_heat_cool", "reheat energy added to already-cooled air", confirmed, poll,
                   econ, window_h, thermal_kw=q, thermal_is="heating", inputs=used,
                   assumptions=["standard air density and specific heat",
                                "the same heat must be removed again by cooling (not counted)"])


def unscheduled_runtime(d, confirmed, poll, econ, window_h):
    kw = _col(d, R.ELECTRIC_POWER)
    if kw is None:
        return _not_quantifiable("unscheduled_runtime", "needs an electric-power (kW) point on this equipment")
    return _finish("unscheduled_runtime", "the equipment's own measured kW while running without need",
                   confirmed, poll, econ, window_h, electric_kw=kw,
                   inputs={"power": R.ELECTRIC_POWER.value}, assumptions=[])


def fan_overpressure(d, confirmed, poll, econ, window_h):
    kw, dsp, sp = _col(d, R.ELECTRIC_POWER), _col(d, R.DUCT_STATIC_PRESSURE), _col(d, R.DUCT_STATIC_PRESSURE_SP)
    if kw is None or dsp is None or sp is None:
        return _not_quantifiable("fan_overpressure", "needs fan kW, duct static and its setpoint")
    ratio = (sp / dsp.where(dsp > 0)).clip(upper=1.0)
    excess = kw * (1.0 - ratio.pow(1.5))
    return _finish("fan_overpressure", "fan kW above what the setpoint static needs (affinity: P ∝ Δp^1.5)",
                   confirmed, poll, econ, window_h, electric_kw=excess,
                   inputs={"power": R.ELECTRIC_POWER.value, "static": R.DUCT_STATIC_PRESSURE.value,
                           "setpoint": R.DUCT_STATIC_PRESSURE_SP.value},
                   assumptions=["fixed system curve (fan power ∝ static pressure^1.5)"])


METHODS = {
    "chw_valve_leak": chw_valve_leak,
    "excess_outdoor_air": excess_outdoor_air,
    "simultaneous_heat_cool": simultaneous_heat_cool,
    "unscheduled_runtime": unscheduled_runtime,
    "fan_overpressure": fan_overpressure,
}


def estimate_impact(method: Optional[str], d: pd.DataFrame, confirmed: pd.Series, poll: float,
                    econ: SiteEconomics, window_h: float) -> Dict[str, Any]:
    if not method:
        return {"status": "not_applicable"}
    fn = METHODS.get(method)
    if fn is None:
        return _not_quantifiable(method, f"no energy model for '{method}' yet")
    try:
        return fn(d, confirmed.reindex(d.index).fillna(False).astype(bool), poll, econ, window_h)
    except Exception as e:  # report, never invent
        return _not_quantifiable(method, f"impact calculation failed: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Priority scores
# ──────────────────────────────────────────────────────────────────────────
COMFORT_RULES = {"VAV-1", "VAV-4", "FC13", "FC7", "FC5", "AHU-SATDEV", "CHW-3", "FC1"}
HEALTH_RULES = {"PID-HUNT-1", "FC4", "CMD-1", "VAV-5", "FC14", "FC15", "VLV-1", "DMP-1",
                "VAV-REHEAT", "VAV-AHU-LEAVE", "CW-APR-1", "CHW-2", "FC2", "FC3",
                "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"}


def _clamp(x: float) -> float:
    return round(max(0.0, min(10.0, x)), 1)


def priority_scores(rule_id: str, fault_pct: Optional[float], impact: Dict[str, Any]) -> Dict[str, Any]:
    pct = float(fault_pct or 0.0)
    out: Dict[str, Any] = {"energy": None, "comfort": None, "health": None, "basis": {}}
    annual = impact.get("projected_annual_cost")
    if annual is not None and annual > 0:
        out["energy"] = _clamp(2.5 * math.log10(max(annual, 1.0) / 100.0))
        out["basis"]["energy"] = f"projected {annual:,.0f} {impact.get('currency', '')}/yr avoidable"
    if rule_id in COMFORT_RULES:
        out["comfort"] = _clamp(pct / 10.0)
        out["basis"]["comfort"] = f"present {pct:.0f}% of running time"
    if rule_id in HEALTH_RULES:
        out["health"] = _clamp(2.0 + pct / 10.0)
        out["basis"]["health"] = f"hardware/control fault present {pct:.0f}% of running time"
    scored = [v for k, v in out.items() if k in ("energy", "comfort", "health") and v is not None]
    out["priority"] = max(scored) if scored else None
    return out
