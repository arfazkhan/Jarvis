"""
Chilled-water plant, district cooling and heat rejection — ported from open-fdd
(MIT — see NOTICE), thresholds in SI.

ARVIS changes:
  * CHW-4 (flow high at max pump) has no universal flow limit — open-fdd's
    1100 gpm default describes one US plant. ``flow_hi`` must be configured.
  * CHW-NOLOAD-1: open-fdd calls the building "satisfied" when zones sit in the
    comfort band — which is exactly what a running chiller achieves, so it fires
    in normal operation. ARVIS flags a chiller running while every mapped
    cooling valve in the building is closed (no chilled-water demand).
  * DC-DT-1 (new): district-cooling primary ΔT below the supply contract's
    minimum. Gulf district-cooling contracts (e.g. Qatar Cool) penalise low ΔT.
  * Condenser-water approach rules use the BMS wet-bulb point, not a web feed.
"""

from __future__ import annotations

from agent_commercial.fdd.gates import GateSpec
from agent_commercial.fdd.rules.base import (
    F_DELTA, PSI_PA, Param, RuleSpec, col, frac, has, p,
)
from agent_commercial.semantics import PointRole as R

CHWS, CHWR, CHWS_SP = R.CHW_SUPPLY_TEMP, R.CHW_RETURN_TEMP, R.CHW_SUPPLY_TEMP_SP
BUILDING_CLG_DEMAND = "ctx:building-max-cooling-valve"


def low_dt(d, prm, ctx):
    dt = col(d, CHWR) - col(d, CHWS)
    return col(d, CHWS).notna() & col(d, CHWR).notna() & (dt < p(prm, "min_dt"))


def dp_low_max_pump(d, prm, ctx):
    return (col(d, R.CHW_DP).notna() & col(d, R.CHW_DP_SP).notna()
            & (col(d, R.CHW_DP) < col(d, R.CHW_DP_SP) - p(prm, "dp_margin"))
            & (frac(d, R.PUMP_SPEED) >= p(prm, "pump_hi")))


def chws_off_setpoint(d, prm, ctx):
    band = p(prm, "sp_band")
    pump_on = (frac(d, R.PUMP_SPEED) > 0.01) if has(d, R.PUMP_SPEED) else True
    s, sp = col(d, CHWS), col(d, CHWS_SP)
    return pump_on & s.notna() & sp.notna() & ((s < sp - band) | (s > sp + band))


def flow_high_max_pump(d, prm, ctx):
    return (col(d, R.CHW_FLOW).notna() & (col(d, R.CHW_FLOW) > p(prm, "flow_hi"))
            & (frac(d, R.PUMP_SPEED) >= p(prm, "pump_hi")))


def chiller_no_demand(d, prm, ctx):
    running = col(d, R.CHILLER_STATUS).fillna(0) > 0.5
    demand = col(d, BUILDING_CLG_DEMAND)
    return running & demand.notna() & (demand <= p(prm, "clg_inactive_max"))


def dc_low_dt(d, prm, ctx):
    dt = col(d, R.DC_PRIMARY_RETURN_TEMP) - col(d, R.DC_PRIMARY_SUPPLY_TEMP)
    return (col(d, R.DC_PRIMARY_SUPPLY_TEMP).notna() & col(d, R.DC_PRIMARY_RETURN_TEMP).notna()
            & (dt < p(prm, "contract_min_dt")))


def _approach(d):
    return col(d, R.CONDENSER_WATER_SUPPLY_TEMP) - col(d, R.OUTSIDE_AIR_WETBULB)


def cw_approach_high(d, prm, ctx):
    return (col(d, R.CONDENSER_WATER_SUPPLY_TEMP).notna() & col(d, R.OUTSIDE_AIR_WETBULB).notna()
            & (frac(d, R.COOLING_TOWER_FAN_SPEED) >= p(prm, "tower_fan_hi"))
            & (_approach(d) > p(prm, "approach_max")))


def cw_fan_excess(d, prm, ctx):
    return (col(d, R.CONDENSER_WATER_SUPPLY_TEMP).notna() & col(d, R.OUTSIDE_AIR_WETBULB).notna()
            & (frac(d, R.COOLING_TOWER_FAN_SPEED) >= p(prm, "tower_fan_hi"))
            & (_approach(d) > p(prm, "cw_approach") + p(prm, "excess_beyond_approach")))


_HYD = lambda s: GateSpec("hydronic_flow", startup_delay_seconds=s)  # noqa: E731
_CHW = ("chiller", "plant")
PUMP_HI = Param("pump_hi", 0.87, "frac", "Pump high-speed threshold")

RULES = [
    RuleSpec("CHW-1", "Low chilled-water ΔT", "plant", _CHW, (CHWS, CHWR), low_dt,
             params=(Param("min_dt", 4.0 * F_DELTA, "°C", "Minimum return − supply ΔT"),),
             confirm_seconds=900, gate=_HYD(900), origin="open-fdd CHW-1",
             summary="Chilled water returns barely warmer than it left — low ΔT syndrome.",
             root_cause_candidates=("coil valves passing / 3-way bypass open", "fouled coils",
                                    "CHW supply setpoint too low", "decoupler / bypass mixing",
                                    "over-pumping"), energy_impact="low_delta_t"),
    RuleSpec("CHW-2", "Loop pressure below setpoint at max pump speed", "plant", ("plant", "pump", "chiller"),
             (R.CHW_DP, R.CHW_DP_SP, R.PUMP_SPEED), dp_low_max_pump,
             params=(Param("dp_margin", 2.2 * PSI_PA, "Pa", "DP below SP by"), PUMP_HI),
             confirm_seconds=300, gate=_HYD(300), origin="open-fdd CHW-2",
             summary="Loop differential pressure stays below setpoint even with pumps near full speed.",
             root_cause_candidates=("DP setpoint too high", "pump impeller wear or air in system",
                                    "strainer blocked", "DP sensor error")),
    RuleSpec("CHW-3", "Chilled-water supply off setpoint", "plant", _CHW, (CHWS, CHWS_SP), chws_off_setpoint,
             optional=(R.PUMP_SPEED,),
             params=(Param("sp_band", 2.2 * F_DELTA, "°C", "Allowed band around setpoint"),),
             confirm_seconds=300, gate=_HYD(600), origin="open-fdd CHW-3",
             summary="Chilled-water supply temperature is outside its setpoint band.",
             root_cause_candidates=("insufficient chiller capacity staged", "chiller fault / limiting",
                                    "district cooling supply warm", "CHWS sensor error")),
    RuleSpec("CHW-4", "Flow high at max pump speed", "plant", ("plant", "pump", "chiller"),
             (R.CHW_FLOW, R.PUMP_SPEED), flow_high_max_pump,
             params=(Param("flow_hi", None, "L/s", "Design maximum flow (site)"), PUMP_HI),
             confirm_seconds=300, gate=_HYD(300), origin="open-fdd CHW-4 (site flow limit required)",
             summary="Loop flow exceeds design while pumps run near full speed — over-pumping.",
             root_cause_candidates=("balancing valves open", "3-way valves bypassing", "DP setpoint too high"),
             energy_impact="over_pumping"),
    RuleSpec("CHW-NOLOAD-1", "Chiller running with no cooling demand", "plant", ("chiller",),
             (R.CHILLER_STATUS, BUILDING_CLG_DEMAND), chiller_no_demand,
             params=(Param("clg_inactive_max", 0.05, "frac", "All cooling valves at or below"),),
             confirm_seconds=1800, gate=GateSpec("always"),
             origin="arvis (replaces open-fdd CHW-NOLOAD-1 comfort-band test)",
             summary="A chiller runs while every mapped cooling valve in the building is closed.",
             root_cause_candidates=("chiller schedule not following load", "chiller in hand",
                                    "minimum-run timers too long"), energy_impact="unscheduled_runtime"),
    RuleSpec("DC-DT-1", "District-cooling ΔT below contract", "plant", ("plant",),
             (R.DC_PRIMARY_SUPPLY_TEMP, R.DC_PRIMARY_RETURN_TEMP), dc_low_dt,
             params=(Param("contract_min_dt", None, "°C", "Contract minimum primary ΔT (site)"),),
             confirm_seconds=1800, gate=_HYD(900), origin="arvis",
             summary="Primary return from the district-cooling ETS is below the contract ΔT — "
                     "penalty exposure and wasted pumping.",
             root_cause_candidates=("building-side low ΔT (see CHW-1)", "ETS control valve passing",
                                    "heat exchanger fouled", "secondary over-pumping"),
             energy_impact="low_delta_t"),
    RuleSpec("CW-APR-1", "High condenser-water approach at full tower fan", "plant",
             ("chiller", "cooling_tower", "plant"),
             (R.CONDENSER_WATER_SUPPLY_TEMP, R.OUTSIDE_AIR_WETBULB, R.COOLING_TOWER_FAN_SPEED),
             cw_approach_high,
             params=(Param("approach_max", 8.0 * F_DELTA, "°C", "Maximum approach at full fan"),
                     Param("tower_fan_hi", 0.95, "frac", "Tower fan full-speed threshold")),
             confirm_seconds=900, gate=_HYD(600), origin="open-fdd CW-APR-1",
             summary="Tower water stays well above wet-bulb even at full fan — tower performance degraded.",
             root_cause_candidates=("tower fill fouled / scaled", "nozzles blocked", "wet-bulb or CW sensor error",
                                    "recirculation of tower discharge air")),
    RuleSpec("CW-FAN-1", "Tower fans chasing an unreachable temperature", "plant",
             ("chiller", "cooling_tower", "plant"),
             (R.CONDENSER_WATER_SUPPLY_TEMP, R.OUTSIDE_AIR_WETBULB, R.COOLING_TOWER_FAN_SPEED),
             cw_fan_excess,
             params=(Param("cw_approach", 7.0 * F_DELTA, "°C", "Design approach"),
                     Param("excess_beyond_approach", 5.0 * F_DELTA, "°C", "Excess beyond approach"),
                     Param("tower_fan_hi", 0.95, "frac", "Tower fan full-speed threshold")),
             confirm_seconds=900, gate=_HYD(600), origin="open-fdd CW-FAN-1",
             summary="Tower fans run flat out for a condenser temperature the weather cannot deliver.",
             root_cause_candidates=("CW setpoint below achievable (wet-bulb + approach)", "tower degraded"),
             energy_impact="tower_fan_excess"),
]
