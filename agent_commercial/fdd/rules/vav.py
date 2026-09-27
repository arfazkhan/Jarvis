"""
Terminal units (VAV / FCU) and zones — ported from open-fdd (MIT — see NOTICE),
thresholds in SI.

ARVIS change: open-fdd's VAV-2 ("unoccupied zone above heating setback") is a
cold-climate rule. In the Gulf the setback runs the other way, so ZONE-SETBACK-1
flags unoccupied zones that are still held cold (cooling never set back).
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from agent_commercial.fdd.gates import AIR_ON_M3S, GateSpec
from agent_commercial.fdd.rules.base import (
    CFM_M3S, F_DELTA, Param, RuleSpec, col, f_to_c, frac, false, has, p,
)
from agent_commercial.semantics import PointRole as R

ZT, DMP, FLOW, RHV = R.ZONE_TEMP, R.TERMINAL_DAMPER, R.TERMINAL_AIRFLOW, R.REHEAT_VALVE
DAT, OAT = R.TERMINAL_DISCHARGE_TEMP, R.OUTSIDE_AIR_TEMP
PARENT_SAT = "ctx:parent-supply-air-temp"
FLOW_ON = Param("flow_on_min", 25 * CFM_M3S, "m³/s", "Airflow-on minimum")


def _air_on(d: pd.DataFrame, flow_min: float) -> pd.Series:
    """Box receiving air: measured airflow above the minimum (True when no
    airflow point — the gate has already established the unit was running)."""
    if has(d, FLOW):
        return col(d, FLOW).fillna(0) > flow_min
    return pd.Series(True, index=d.index)


def zone_band(d, prm, ctx):
    zt = col(d, ZT)
    return zt.notna() & ((zt < p(prm, "zone_lo")) | (zt > p(prm, "zone_hi")))


def zone_setback(d, prm, ctx):
    zt = col(d, ZT)
    unocc = col(d, R.OCCUPANCY).fillna(1) <= 0.05
    return zt.notna() & unocc & (zt < p(prm, "setback_min")) & _air_on(d, p(prm, "flow_on_min"))


def reheat_warm(d, prm, ctx):
    return (_air_on(d, p(prm, "flow_on_min")) & col(d, OAT).notna()
            & (col(d, OAT) > p(prm, "reheat_oat")) & (frac(d, RHV) > p(prm, "reheat_pct")))


def damper_pinned(d, prm, ctx):
    roll = max(2, int(round(p(prm, "sustain_hours") * 3600 / max(ctx.poll_seconds, 1))))
    dmp = frac(d, DMP)
    full = p(prm, "full_open_pct")
    return (_air_on(d, p(prm, "flow_on_min")) & (dmp > full)
            & (dmp.rolling(roll, min_periods=roll).min() > full))


def flow_closed_damper(d, prm, ctx):
    return col(d, FLOW).notna() & (col(d, FLOW) > p(prm, "flow_implausible")) & (frac(d, DMP) < 0.10)


def reheat_free_cool(d, prm, ctx):
    oat = col(d, OAT)
    return oat.notna() & (oat < p(prm, "free_cool_oat")) & (frac(d, RHV) > p(prm, "reheat_pct"))


def reheat_no_rise(d, prm, ctx):
    inlet = col(d, R.TERMINAL_INLET_TEMP) if has(d, R.TERMINAL_INLET_TEMP) else col(d, PARENT_SAT)
    ctx.notes["inlet_source"] = (R.TERMINAL_INLET_TEMP.value if has(d, R.TERMINAL_INLET_TEMP)
                                 else PARENT_SAT)
    rise = col(d, DAT) - inlet
    return (_air_on(d, p(prm, "flow_on_min")) & col(d, DAT).notna() & inlet.notna()
            & (frac(d, RHV) > p(prm, "reheat_cmd")) & (rise < p(prm, "min_rise")))


def leave_vs_ahu(d, prm, ctx):
    leave, ahu = col(d, DAT), col(d, PARENT_SAT)
    return (_air_on(d, p(prm, "flow_on_min")) & leave.notna() & ahu.notna()
            & ((leave - ahu).abs() > p(prm, "delta")))


_TERM = ("vav", "fcu")
_FAN = lambda s=300: GateSpec("fan_running", startup_delay_seconds=s)  # noqa: E731

RULES = [
    RuleSpec("VAV-1", "Zone outside comfort band", "vav", ("vav", "fcu"), (ZT,), zone_band,
             params=(Param("zone_lo", f_to_c(70.0), "°C", "Zone low"),
                     Param("zone_hi", f_to_c(75.0), "°C", "Zone high")),
             confirm_seconds=900, gate=GateSpec("conditional"), origin="open-fdd VAV-1",
             summary="Zone temperature sits outside the comfort band while the zone is served.",
             root_cause_candidates=("terminal capacity insufficient", "zone setpoint changed / overridden",
                                    "damper or valve stuck", "zone sensor error or poor location",
                                    "AHU supply air too warm")),
    RuleSpec("ZONE-SETBACK-1", "Cooling not set back when unoccupied", "vav", ("vav", "fcu"),
             (ZT, R.OCCUPANCY), zone_setback,
             params=(Param("setback_min", 24.0, "°C", "Unoccupied zone should drift above"), FLOW_ON),
             confirm_seconds=1800, gate=GateSpec("always"), origin="arvis (Gulf counterpart of open-fdd VAV-2)",
             summary="Zone is held cold while unoccupied — cooling setback is not being applied.",
             root_cause_candidates=("occupancy schedule not applied", "unoccupied setpoint too low",
                                    "zone in override"), energy_impact="unscheduled_runtime"),
    RuleSpec("VAV-3", "Reheat in warm weather", "vav", ("vav",), (OAT, RHV), reheat_warm,
             params=(Param("reheat_oat", f_to_c(78.0), "°C", "Warm OAT"),
                     Param("reheat_pct", 0.52, "frac", "Reheat open"), FLOW_ON),
             confirm_seconds=300, gate=_FAN(), origin="open-fdd VAV-3",
             summary="Reheat valve open while it is hot outside — cooling and reheating the same air.",
             root_cause_candidates=("minimum airflow too high (overcooling)", "reheat valve passing",
                                    "zone setpoint conflict"), energy_impact="simultaneous_heat_cool"),
    RuleSpec("VAV-4", "Damper pinned fully open", "vav", ("vav",), (DMP,), damper_pinned,
             optional=(FLOW,),
             params=(Param("full_open_pct", 0.975, "frac", "Full open"),
                     Param("sustain_hours", 1.5, "h", "Sustained for"), FLOW_ON),
             confirm_seconds=900, gate=GateSpec("control_loop", startup_delay_seconds=300),
             origin="open-fdd VAV-4",
             summary="The box damper sits fully open for hours — the zone cannot be satisfied.",
             root_cause_candidates=("zone load exceeds box capacity", "AHU supply static too low",
                                    "damper actuator failed open", "airflow sensor error")),
    RuleSpec("VAV-5", "Airflow reading with damper closed", "vav", ("vav",), (FLOW, DMP), flow_closed_damper,
             params=(Param("flow_implausible", 50 * CFM_M3S, "m³/s", "Implausible flow"),),
             confirm_seconds=900, gate=_FAN(), origin="open-fdd VAV-5",
             summary="The box reports airflow while its damper is nearly closed — an airflow sensor bias.",
             root_cause_candidates=("airflow sensor offset / needs zeroing", "damper feedback wrong",
                                    "damper linkage slipped")),
    RuleSpec("VAV-6", "Reheat while free cooling is available", "vav", ("vav",), (OAT, RHV), reheat_free_cool,
             params=(Param("free_cool_oat", f_to_c(65.0), "°C", "Free-cool OAT"),
                     Param("reheat_pct", 0.25, "frac", "Reheat open")),
             confirm_seconds=900, gate=_FAN(), origin="open-fdd VAV-6",
             summary="Reheat is open while outdoor air is cool enough for free cooling.",
             root_cause_candidates=("minimum airflow too high", "supply air too cold"),
             energy_impact="simultaneous_heat_cool"),
    RuleSpec("VAV-REHEAT", "Reheat open but no temperature rise", "vav", ("vav",),
             (RHV, DAT, (R.TERMINAL_INLET_TEMP, PARENT_SAT)), reheat_no_rise,
             params=(Param("reheat_cmd", 0.30, "frac", "Reheat open"),
                     Param("min_rise", 3.0 * F_DELTA, "°C", "Minimum temperature rise"), FLOW_ON),
             confirm_seconds=900, gate=_FAN(600), origin="open-fdd VAV-REHEAT",
             summary="The reheat valve is open but the air leaving the box is barely warmer.",
             root_cause_candidates=("reheat valve stuck closed", "no hot water to the coil",
                                    "discharge sensor error")),
    RuleSpec("VAV-AHU-LEAVE", "Box discharge far from its AHU supply air", "vav", ("vav",),
             (DAT, PARENT_SAT), leave_vs_ahu,
             params=(Param("delta", 8.0 * F_DELTA, "°C", "Allowed difference"), FLOW_ON),
             confirm_seconds=900, gate=_FAN(600), origin="open-fdd VAV-AHU-LEAVE",
             summary="Air leaving the box differs a lot from the AHU supply air feeding it.",
             root_cause_candidates=("reheat valve passing or stuck", "discharge sensor error",
                                    "box fed by a different AHU than mapped")),
]
