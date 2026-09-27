"""
Air handling units / FAHUs — ASHRAE Guideline 36 FC1–FC15 and related patterns,
ported from open-fdd (MIT — see NOTICE). Thresholds converted to SI.

Gulf adaptations (each marked "ARVIS:" below):
  * FC13/FC14 on units with no OA-damper point (typical 100%-fresh-air units):
    GL36's "coil should be inactive" states assume an economizer. Without one,
    the coil should be inactive whenever its valve is closed — which is exactly
    the leaking-CHW-valve case that matters most in the Gulf.
  * FC13 full-cooling threshold 0.95 (open-fdd ships 0.01 while labelling it
    "GL36 99%", which makes FC13 fire at 1 % valve).
  * Economizer-sequence rules (FC8–FC12, ECON-1/2) apply only when the unit's
    commissioned design says it has an economizer.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from agent_commercial.fdd.gates import GateSpec
from agent_commercial.fdd.rules.base import (
    CFM_M3S, F_DELTA, FAN_ANY, INWC_PA, Param, RuleContext, RuleSpec,
    col, f_to_c, fan, frac, false, has, p,
)
from agent_commercial.semantics import PointRole as R

MIX_TOL = 1.15 * F_DELTA            # sensor error ε (°C)
DELTA_SUPPLY_FAN = 0.55 * F_DELTA   # supply-fan heat rise ΔTSF (°C)
AHU_MIN_OA_DPR = 0.05
FAN_ON_MIN = 0.01

SAT, SATSP, MAT, RAT, OAT = (R.SUPPLY_AIR_TEMP, R.SUPPLY_AIR_TEMP_SP, R.MIXED_AIR_TEMP,
                             R.RETURN_AIR_TEMP, R.OUTSIDE_AIR_TEMP)
OAD, CLG, HTG = R.OUTSIDE_AIR_DAMPER, R.COOLING_VALVE, R.HEATING_VALVE


def _eps(key: str, label: str, default: float = MIX_TOL) -> Param:
    return Param(key, default, "°C", label)


MODE_DELAY = Param("mode_delay_min", 0.0, "min", "Mode-change suspension (GL36 default 30)")
DTSF = Param("delta_supply_fan", DELTA_SUPPLY_FAN, "°C", "Supply-fan heat rise ΔTSF")
ECON_MIN = Param("econ_min_pos", AHU_MIN_OA_DPR, "frac", "Economizer minimum-position threshold")
ECON_FULL = Param("econ_full_open", 0.90, "frac", "Economizer full-open threshold")
CLG_ON = Param("clg_on_min", 0.01, "frac", "Cooling ON threshold")
CLG_INACTIVE = Param("clg_inactive_max", 0.10, "frac", "Cooling inactive ceiling")
FAN_ON = Param("fan_on_min", FAN_ON_MIN, "frac", "Fan-on threshold")
HTG_ON = Param("htg_on_min", 0.01, "frac", "Heating ON threshold")

_FAN_GATE = lambda s=600: GateSpec("fan_running", startup_delay_seconds=s)  # noqa: E731


def _mode_stable(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    """False during the GL36 ModeDelay after an AHU operating-state change."""
    delay_min = float(prm.get("mode_delay_min", 0.0) or 0.0)
    if delay_min <= 0 or d.empty:
        return pd.Series(True, index=d.index)
    htg, clg, econ, f = frac(d, HTG), frac(d, CLG), frac(d, OAD), fan(d)
    fan_on = float(prm.get("fan_on_min", FAN_ON_MIN))
    econ_min = float(prm.get("econ_min_pos", AHU_MIN_OA_DPR))
    clg_on = float(prm.get("clg_on_min", 0.01))
    htg_on = float(prm.get("htg_on_min", 0.01))
    state = pd.Series(0, index=d.index, dtype=int)
    state[(f > fan_on) & (htg > htg_on) & (clg <= clg_on)] = 1
    state[(f > fan_on) & (htg <= htg_on) & (clg <= clg_on) & (econ > econ_min)] = 2
    state[(f > fan_on) & (htg <= htg_on) & (clg > clg_on) & (econ > econ_min)] = 3
    state[(f > fan_on) & (htg <= htg_on) & (clg > clg_on) & (econ <= econ_min)] = 4
    changed = state.ne(state.shift()).fillna(False)
    if len(changed):
        changed.iloc[0] = False
    samples = max(1, int(np.ceil(delay_min * 60.0 / max(float(ctx.poll_seconds), 1.0))))
    return ~changed.astype(int).rolling(samples, min_periods=1).max().astype(bool)


def _g36(raw: pd.Series, d, prm, ctx) -> pd.Series:
    return raw.fillna(False) & _mode_stable(d, prm, ctx)


def fc1(d, prm, ctx):
    fan_hi = 1.0 - p(prm, "eps_vfd_spd")
    raw = (col(d, R.DUCT_STATIC_PRESSURE).notna() & col(d, R.DUCT_STATIC_PRESSURE_SP).notna()
           & (col(d, R.DUCT_STATIC_PRESSURE) < col(d, R.DUCT_STATIC_PRESSURE_SP) - p(prm, "eps_dsp"))
           & (frac(d, R.SUPPLY_FAN_SPEED) >= fan_hi))
    return _g36(raw, d, prm, ctx)


def fc2(d, prm, ctx):
    raw = ((fan(d) > p(prm, "fan_on_min"))
           & col(d, MAT).notna() & col(d, OAT).notna() & col(d, RAT).notna()
           & ((col(d, MAT) + p(prm, "eps_mat"))
              < np.minimum(col(d, RAT) - p(prm, "eps_rat"), col(d, OAT) - p(prm, "eps_oat"))))
    return _g36(raw, d, prm, ctx)


def fc3(d, prm, ctx):
    raw = ((fan(d) > p(prm, "fan_on_min"))
           & col(d, MAT).notna() & col(d, OAT).notna() & col(d, RAT).notna()
           & ((col(d, MAT) - p(prm, "eps_mat"))
              > np.maximum(col(d, RAT) + p(prm, "eps_rat"), col(d, OAT) + p(prm, "eps_oat"))))
    return _g36(raw, d, prm, ctx)


def fc4(d, prm, ctx):
    """Operating-state entries per hour above ΔOSmax (GL36 hunting between modes)."""
    htg, clg, econ, f = frac(d, HTG), frac(d, CLG), frac(d, OAD), fan(d)
    if not isinstance(d.index, pd.DatetimeIndex):
        return false(d)
    modes = pd.DataFrame(index=d.index)
    modes["heating"] = ((htg > 0) & (clg == 0) & (f > 0) & (econ <= AHU_MIN_OA_DPR)).astype(int)
    modes["econ_only"] = ((htg == 0) & (clg == 0) & (f > 0) & (econ > AHU_MIN_OA_DPR)).astype(int)
    modes["econ_mech"] = ((htg == 0) & (clg > 0) & (f > 0) & (econ > AHU_MIN_OA_DPR)).astype(int)
    modes["mech_only"] = ((htg == 0) & (clg > 0) & (f > 0) & (econ <= AHU_MIN_OA_DPR)).astype(int)
    entries = modes.eq(1) & modes.shift().ne(1)
    hourly = entries.resample("1h").sum()
    flagged = hourly[(hourly > p(prm, "delta_os_max")).any(axis=1)].index
    return pd.Series(d.index.floor("1h").isin(flagged), index=d.index)


def fc5(d, prm, ctx):
    raw = (col(d, SAT).notna() & col(d, MAT).notna()
           & (fan(d) > p(prm, "fan_on_min")) & (frac(d, HTG) > p(prm, "htg_on_min"))
           & ((col(d, SAT) + p(prm, "eps_sat"))
              <= (col(d, MAT) - p(prm, "eps_mat") + p(prm, "delta_supply_fan"))))
    return _g36(raw, d, prm, ctx)


def fc6(d, prm, ctx):
    rat_oat = (col(d, RAT) - col(d, OAT)).abs()
    pct_oa = ((col(d, MAT) - col(d, RAT))
              / (col(d, OAT) - col(d, RAT)).replace(0, np.nan)).clip(lower=0)
    perc_oamin = p(prm, "min_oa_design") / col(d, R.SUPPLY_AIRFLOW).replace(0, np.nan)
    raw = (col(d, MAT).notna() & col(d, OAT).notna() & col(d, RAT).notna()
           & col(d, R.SUPPLY_AIRFLOW).notna()
           & (rat_oat >= p(prm, "delta_t_min")) & ((pct_oa - perc_oamin).abs() > p(prm, "eps_airflow"))
           & (fan(d) > p(prm, "fan_on_min")))
    return _g36(raw, d, prm, ctx)


def fc7(d, prm, ctx):
    raw = (col(d, SAT).notna() & col(d, SATSP).notna() & (fan(d) > p(prm, "fan_on_min"))
           & (col(d, SAT) < col(d, SATSP) - p(prm, "eps_sat"))
           & (frac(d, HTG) >= p(prm, "htg_full_min")))
    return _g36(raw, d, prm, ctx)


def fc8(d, prm, ctx):
    err = (col(d, SAT) - p(prm, "delta_supply_fan") - col(d, MAT)).abs()
    tol = float(np.sqrt(p(prm, "eps_sat") ** 2 + p(prm, "eps_mat") ** 2))
    raw = (col(d, SAT).notna() & col(d, MAT).notna()
           & (frac(d, OAD) > p(prm, "econ_min_pos")) & (frac(d, CLG) < p(prm, "clg_inactive_max"))
           & (err > tol))
    return _g36(raw, d, prm, ctx)


def fc9(d, prm, ctx):
    raw = (col(d, OAT).notna() & col(d, SATSP).notna()
           & (frac(d, OAD) > p(prm, "econ_min_pos")) & (frac(d, CLG) < p(prm, "clg_inactive_max"))
           & ((col(d, OAT) - p(prm, "eps_oat"))
              > (col(d, SATSP) - p(prm, "delta_supply_fan") + p(prm, "eps_sat"))))
    return _g36(raw, d, prm, ctx)


def fc10(d, prm, ctx):
    tol = float(np.sqrt(p(prm, "eps_mat") ** 2 + p(prm, "eps_oat") ** 2))
    raw = (col(d, MAT).notna() & col(d, OAT).notna()
           & (frac(d, CLG) > p(prm, "clg_on_min")) & (frac(d, OAD) > p(prm, "econ_full_open"))
           & ((col(d, MAT) - col(d, OAT)).abs() > tol))
    return _g36(raw, d, prm, ctx)


def fc11(d, prm, ctx):
    raw = (col(d, OAT).notna() & col(d, SATSP).notna()
           & (frac(d, CLG) > p(prm, "clg_on_min")) & (frac(d, OAD) > p(prm, "econ_full_open"))
           & ((col(d, OAT) + p(prm, "eps_oat"))
              < (col(d, SATSP) - p(prm, "delta_supply_fan") - p(prm, "eps_sat"))))
    return _g36(raw, d, prm, ctx)


def fc12(d, prm, ctx):
    econ = frac(d, OAD)
    raw = (col(d, SAT).notna() & col(d, MAT).notna() & (frac(d, CLG) > p(prm, "clg_on_min"))
           & ((col(d, SAT) - p(prm, "eps_sat") - p(prm, "delta_supply_fan"))
              > (col(d, MAT) + p(prm, "eps_mat")))
           & ((econ <= p(prm, "econ_min_pos")) | (econ > p(prm, "econ_full_open"))))
    return _g36(raw, d, prm, ctx)


def _mech_cooling_state(d, prm) -> pd.Series:
    """OS#3/OS#4 per GL36; ARVIS: with no OA-damper point the unit has no
    economizer, so any cooling is mechanical-only (OS#4)."""
    if not has(d, OAD):
        return pd.Series(True, index=d.index)
    econ = frac(d, OAD)
    return (econ <= p(prm, "econ_min_pos")) | (econ > p(prm, "econ_full_open"))


def fc13(d, prm, ctx):
    raw = (col(d, SAT).notna() & col(d, SATSP).notna()
           & (frac(d, CLG) >= p(prm, "clg_full_min"))
           & (col(d, SAT) > col(d, SATSP) + p(prm, "eps_sat"))
           & _mech_cooling_state(d, prm))
    return _g36(raw, d, prm, ctx)


def fc14(d, prm, ctx):
    delta = col(d, R.COOLING_COIL_ENTERING_TEMP) - col(d, R.COOLING_COIL_LEAVING_TEMP)
    tol = float(np.sqrt(p(prm, "eps_ccet") ** 2 + p(prm, "eps_cclt") ** 2)) + p(prm, "delta_supply_fan")
    clg_off = frac(d, CLG) < p(prm, "clg_inactive_max")
    if has(d, OAD):
        inactive = (((frac(d, OAD) > p(prm, "econ_min_pos")) & clg_off)
                    | ((frac(d, HTG) > p(prm, "htg_on_min")) & (fan(d) > 0)))
    else:
        # ARVIS: no economizer → the coil must be inactive whenever its valve is closed.
        inactive = clg_off & (fan(d) > 0)
    raw = (col(d, R.COOLING_COIL_ENTERING_TEMP).notna() & col(d, R.COOLING_COIL_LEAVING_TEMP).notna()
           & (delta >= tol) & inactive)
    return _g36(raw, d, prm, ctx)


def fc15(d, prm, ctx):
    econ, clg = frac(d, OAD), frac(d, CLG)
    delta = col(d, R.HEATING_COIL_ENTERING_TEMP) - col(d, R.HEATING_COIL_LEAVING_TEMP)
    tol = float(np.sqrt(p(prm, "eps_hcet") ** 2 + p(prm, "eps_hclt") ** 2)) + p(prm, "delta_supply_fan")
    raw = (col(d, R.HEATING_COIL_ENTERING_TEMP).notna() & col(d, R.HEATING_COIL_LEAVING_TEMP).notna()
           & (delta >= tol)
           & (((econ > p(prm, "econ_min_pos")) & (clg < p(prm, "clg_inactive_max")))
              | ((clg > p(prm, "clg_on_min")) & (econ <= p(prm, "econ_min_pos")))
              | ((clg > p(prm, "clg_on_min")) & (econ > p(prm, "econ_full_open")))))
    return _g36(raw, d, prm, ctx)


def sat_dev(d, prm, ctx):
    return (col(d, SAT).notna() & col(d, SATSP).notna()
            & ((col(d, SAT) - col(d, SATSP)).abs() > p(prm, "sat_dev_err")))


def duct_high(d, prm, ctx):
    return (col(d, R.DUCT_STATIC_PRESSURE).notna() & col(d, R.DUCT_STATIC_PRESSURE_SP).notna()
            & (col(d, R.DUCT_STATIC_PRESSURE)
               > col(d, R.DUCT_STATIC_PRESSURE_SP) + p(prm, "duct_high_margin")))


def simul_heat_cool(d, prm, ctx):
    thr = p(prm, "valve_open_pct")
    return (frac(d, HTG) > thr) & (frac(d, CLG) > thr)


def cmd_status(d, prm, ctx):
    if has(d, R.SUPPLY_FAN_CMD):
        cmd_on = col(d, R.SUPPLY_FAN_CMD).fillna(0) > 0.5
    else:
        cmd_on = frac(d, R.SUPPLY_FAN_SPEED) >= 0.05
    status = col(d, R.SUPPLY_FAN_STATUS)
    return status.notna() & (cmd_on != (status.fillna(0) > 0.5))


def oa_low(d, prm, ctx):
    oa_frac = (col(d, MAT) - col(d, RAT)) / (col(d, OAT) - col(d, RAT)).replace(0, np.nan)
    return ((fan(d) > FAN_ON_MIN) & col(d, OAT).notna() & col(d, RAT).notna() & col(d, MAT).notna()
            & ((col(d, RAT) - col(d, OAT)).abs() > p(prm, "oat_rat_guard"))
            & (oa_frac < p(prm, "min_oa_frac")))


def damper_leak(d, prm, ctx):
    return (col(d, OAT).notna() & col(d, MAT).notna() & (frac(d, OAD) <= 0.05)
            & ((col(d, MAT) - col(d, OAT)).abs() < p(prm, "leak_delta")))


def valve_leak(d, prm, ctx):
    closed = frac(d, CLG) <= 0.05
    sat = col(d, SAT)
    below_sp = sat.notna() & col(d, SATSP).notna() & (sat < col(d, SATSP) - p(prm, "sat_err"))
    below_mat = false(d)
    if has(d, MAT):
        below_mat = sat.notna() & col(d, MAT).notna() & (sat < col(d, MAT) - p(prm, "mat_leak_delta"))
    return closed & (below_sp | below_mat)


def econ_stuck_closed(d, prm, ctx):
    return ((fan(d) > FAN_ON_MIN) & col(d, OAD).notna() & col(d, OAT).notna()
            & (frac(d, OAD) < 0.05) & (col(d, OAT) > p(prm, "econ1_oat_min")))


def econ_unfavorable(d, prm, ctx):
    return (col(d, OAT).notna() & col(d, OAD).notna()
            & (col(d, OAT) > p(prm, "econ2_oat_hi")) & (frac(d, OAD) > p(prm, "econ2_damper")))


def econ_low_oa(d, prm, ctx):
    oa_pct = ((col(d, MAT) - col(d, RAT))
              / (col(d, OAT) - col(d, RAT)).replace(0, np.nan) * 100.0)
    return ((fan(d) > FAN_ON_MIN) & col(d, MAT).notna() & col(d, RAT).notna() & col(d, OAT).notna()
            & ((col(d, RAT) - col(d, OAT)).abs() > p(prm, "oat_rat_guard"))
            & (oa_pct < p(prm, "oa_min_pct")))


def always_on(d, prm, ctx):
    """Fan (or pump/chiller) proven on for ≥ always_on_pct of the whole window."""
    for role, thr in ((R.SUPPLY_FAN_STATUS, 0.5), (R.CHILLER_STATUS, 0.5)):
        if has(d, role):
            on = col(d, role).fillna(0) > thr
            ctx.notes["proof"] = role.value
            if float(on.mean()) >= p(prm, "always_on_pct"):
                return on
            return false(d)
    return false(d)


_AHU = ("ahu",)
_G36 = "open-fdd {} (ASHRAE G36 {})"
_LEAK = ("chilled-water valve passing / not seating", "valve actuator failed or unlinked",
         "coil sensor error")

RULES = [
    RuleSpec("FC1", "Duct static below setpoint at full fan speed", "ahu", _AHU,
             (R.DUCT_STATIC_PRESSURE, R.DUCT_STATIC_PRESSURE_SP, R.SUPPLY_FAN_SPEED), fc1,
             params=(Param("eps_dsp", 0.12 * INWC_PA, "Pa", "Duct static error εDSP"),
                     Param("eps_vfd_spd", 0.13, "frac", "VFD speed error εVFDSPD"), MODE_DELAY),
             confirm_seconds=300, gate=_FAN_GATE(300), origin=_G36.format("FC1", "A"),
             summary="Duct static stays below setpoint although the supply fan is near full speed.",
             root_cause_candidates=("duct leak or open access door", "fan belt slip / fan degradation",
                                    "static pressure sensor error", "setpoint too high for the system",
                                    "dirty filter or coil restricting airflow"),
             energy_impact="fan_full_speed"),
    RuleSpec("FC2", "Mixed air below OAT/RAT envelope", "ahu", _AHU,
             (MAT, OAT, RAT, FAN_ANY), fc2,
             params=(_eps("eps_mat", "MAT sensor error"), _eps("eps_rat", "RAT sensor error"),
                     _eps("eps_oat", "OAT sensor error"), FAN_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC2", "B"),
             summary="Mixed-air temperature is colder than both outdoor and return air — physically impossible.",
             root_cause_candidates=("MAT sensor error or poor location", "RAT/OAT sensor error",
                                    "stratification in the mixing box")),
    RuleSpec("FC3", "Mixed air above OAT/RAT envelope", "ahu", _AHU,
             (MAT, OAT, RAT, FAN_ANY), fc3,
             params=(_eps("eps_mat", "MAT sensor error"), _eps("eps_rat", "RAT sensor error"),
                     _eps("eps_oat", "OAT sensor error"), FAN_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC3", "C"),
             summary="Mixed-air temperature is warmer than both outdoor and return air — physically impossible.",
             root_cause_candidates=("MAT sensor error or poor location", "RAT/OAT sensor error",
                                    "preheat coil leaking upstream of MAT sensor")),
    RuleSpec("FC4", "Too many operating-mode changes per hour", "ahu", _AHU,
             (OAD, CLG, FAN_ANY), fc4,
             params=(Param("delta_os_max", 5.0, "count/h", "Max mode changes per hour"), MODE_DELAY),
             confirm_seconds=3600, gate=GateSpec("control_loop", startup_delay_seconds=300),
             origin=_G36.format("FC4", "N"),
             summary="The unit keeps switching between heating / economizer / mechanical cooling.",
             root_cause_candidates=("control deadbands too narrow", "PID tuning", "setpoint conflicts")),
    RuleSpec("FC5", "Supply air cold while heating", "ahu", _AHU,
             (SAT, MAT, FAN_ANY, HTG), fc5,
             params=(_eps("eps_sat", "SAT sensor error"), _eps("eps_mat", "MAT sensor error"),
                     DTSF, HTG_ON, FAN_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC5", "D"),
             summary="Supply air is no warmer than mixed air while heating is commanded.",
             root_cause_candidates=("heating valve stuck closed", "no hot water supply", "SAT/MAT sensor error")),
    RuleSpec("FC6", "Outdoor-air fraction differs from design minimum", "ahu", _AHU,
             (MAT, OAT, RAT, R.SUPPLY_AIRFLOW), fc6,
             params=(Param("eps_airflow", 0.15, "frac", "Airflow error εF"),
                     Param("delta_t_min", 5.0 * F_DELTA, "°C", "Minimum |OAT−RAT|"),
                     Param("min_oa_design", None, "m³/s", "Design minimum outdoor airflow (site)"),
                     FAN_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC6", "E"),
             summary="Estimated outdoor-air fraction differs from the design minimum ventilation rate.",
             root_cause_candidates=("minimum OA damper position wrong", "OA damper actuator fault",
                                    "airflow station error")),
    RuleSpec("FC7", "Supply air below setpoint at full heating", "ahu", _AHU,
             (SAT, SATSP, FAN_ANY, HTG), fc7,
             params=(_eps("eps_sat", "SAT sensor error", 1.0 * F_DELTA),
                     Param("htg_full_min", 0.90, "frac", "Full-heating threshold"), FAN_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC7", "E"),
             summary="Supply air stays below setpoint even with heating fully open.",
             root_cause_candidates=("heating capacity insufficient", "hot water temperature low",
                                    "heating valve stuck")),
    RuleSpec("FC8", "Supply/mixed air mismatch in economizer mode", "ahu", _AHU,
             (SAT, MAT, OAD, CLG), fc8,
             params=(_eps("eps_sat", "SAT sensor error"), _eps("eps_mat", "MAT sensor error"),
                     DTSF, ECON_MIN, CLG_INACTIVE, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC8", "F"),
             requires_design="economizer",
             summary="In economizer-only mode, supply air differs from mixed air by more than fan heat.",
             root_cause_candidates=("SAT or MAT sensor error", "cooling valve leaking", "heating valve leaking")),
    RuleSpec("FC9", "Outdoor air too warm for free cooling", "ahu", _AHU,
             (OAT, SATSP, OAD, CLG), fc9,
             params=(_eps("eps_oat", "OAT sensor error"), _eps("eps_sat", "SAT sensor error"),
                     DTSF, ECON_MIN, CLG_INACTIVE, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC9", "G"),
             requires_design="economizer",
             summary="Economizing without mechanical cooling while outdoor air is too warm to meet setpoint.",
             root_cause_candidates=("economizer high-limit setting wrong", "OAT sensor error")),
    RuleSpec("FC10", "Mixed/outdoor air mismatch with economizer open", "ahu", _AHU,
             (MAT, OAT, OAD, CLG), fc10,
             params=(_eps("eps_mat", "MAT sensor error"), _eps("eps_oat", "OAT sensor error"),
                     ECON_FULL, CLG_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC10", "H"),
             requires_design="economizer",
             summary="With the OA damper fully open, mixed air should equal outdoor air but does not.",
             root_cause_candidates=("OA damper not actually open (linkage/actuator)", "MAT or OAT sensor error")),
    RuleSpec("FC11", "Outdoor air too cold for economizer + cooling", "ahu", _AHU,
             (OAT, SATSP, OAD, CLG), fc11,
             params=(_eps("eps_oat", "OAT sensor error"), _eps("eps_sat", "SAT sensor error"),
                     DTSF, ECON_FULL, CLG_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC11", "I"),
             requires_design="economizer",
             summary="Mechanical cooling with a full economizer although outdoor air alone is cold enough.",
             root_cause_candidates=("economizer sequence error", "OAT sensor error")),
    RuleSpec("FC12", "Supply air warmer than mixed air while cooling", "ahu", _AHU,
             (SAT, MAT, OAD, CLG), fc12,
             params=(_eps("eps_sat", "SAT sensor error"), _eps("eps_mat", "MAT sensor error"),
                     DTSF, ECON_MIN, ECON_FULL, CLG_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC12", "J"),
             requires_design="economizer",
             summary="Supply air is warmer than mixed air plus fan heat while cooling is on.",
             root_cause_candidates=("cooling coil not cooling (no CHW flow)", "heating valve leaking",
                                    "SAT/MAT sensor error")),
    RuleSpec("FC13", "Supply air above setpoint at full cooling", "ahu", _AHU,
             (SAT, SATSP, CLG), fc13, optional=(OAD,),
             params=(_eps("eps_sat", "SAT sensor error", 1.0 * F_DELTA),
                     Param("clg_full_min", 0.95, "frac", "Full-cooling threshold (GL36 99%)"),
                     ECON_MIN, ECON_FULL, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC13", "K"),
             summary="Supply air stays above setpoint even with the cooling valve fully open.",
             root_cause_candidates=("chilled-water supply too warm or flow too low", "coil fouled",
                                    "cooling valve / actuator not opening", "coil undersized for load"),
             energy_impact="cooling_shortfall"),
    RuleSpec("FC14", "Cooling coil cooling while it should be off", "ahu", _AHU,
             (R.COOLING_COIL_ENTERING_TEMP, R.COOLING_COIL_LEAVING_TEMP, CLG), fc14, optional=(OAD, HTG),
             params=(_eps("eps_ccet", "Coil entering sensor error"), _eps("eps_cclt", "Coil leaving sensor error"),
                     DTSF, ECON_MIN, CLG_INACTIVE, HTG_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC14", "L"),
             summary="Air cools across the chilled-water coil although its valve is closed — a passing valve.",
             root_cause_candidates=_LEAK, energy_impact="chw_valve_leak"),
    RuleSpec("FC15", "Heating coil heating while it should be off", "ahu", _AHU,
             (R.HEATING_COIL_ENTERING_TEMP, R.HEATING_COIL_LEAVING_TEMP, OAD, CLG), fc15,
             params=(_eps("eps_hcet", "Coil entering sensor error"), _eps("eps_hclt", "Coil leaving sensor error"),
                     DTSF, ECON_MIN, ECON_FULL, CLG_INACTIVE, CLG_ON, MODE_DELAY),
             confirm_seconds=600, gate=_FAN_GATE(), origin=_G36.format("FC15", "M"),
             summary="Air heats across the hot-water coil although heating should be off — a passing valve.",
             root_cause_candidates=("hot-water valve passing", "valve actuator failed", "coil sensor error"),
             energy_impact="simultaneous_heat_cool"),
    RuleSpec("AHU-SATDEV", "Supply air far from setpoint", "ahu", _AHU, (SAT, SATSP), sat_dev,
             params=(Param("sat_dev_err", 5.0 * F_DELTA, "°C", "SAT deviation"),),
             confirm_seconds=600, gate=_FAN_GATE(), origin="open-fdd AHU-SATDEV",
             summary="Supply-air temperature deviates from setpoint for a sustained period.",
             root_cause_candidates=("insufficient CHW capacity or flow", "control loop not tracking",
                                    "valve / actuator fault", "SAT sensor error")),
    RuleSpec("AHU-DUCTHI", "Duct static above setpoint", "ahu", _AHU,
             (R.DUCT_STATIC_PRESSURE, R.DUCT_STATIC_PRESSURE_SP), duct_high,
             params=(Param("duct_high_margin", 0.25 * INWC_PA, "Pa", "High margin"),
                     Param("pressure_on_min", 0.20 * INWC_PA, "Pa", "Pressure-on evidence")),
             confirm_seconds=300, gate=GateSpec("conditional"), origin="open-fdd AHU-DUCTHI",
             summary="Duct static pressure runs above setpoint — wasted fan energy and noise.",
             root_cause_candidates=("static pressure control loop not tracking", "VAV boxes closed",
                                    "fan VFD in hand/override"), energy_impact="fan_overpressure"),
    RuleSpec("AHU-SIMUL", "Heating and cooling at the same time", "ahu", _AHU, (HTG, CLG), simul_heat_cool,
             params=(Param("valve_open_pct", 0.10, "frac", "Valve open threshold"),),
             confirm_seconds=300, gate=_FAN_GATE(300), origin="open-fdd AHU-SIMUL",
             summary="Heating and cooling valves are both open at once.",
             root_cause_candidates=("overlapping heating/cooling deadbands", "valve passing", "sequence error"),
             energy_impact="simultaneous_heat_cool"),
    RuleSpec("CMD-1", "Fan command and status disagree", "ahu", ("ahu", "fcu"),
             (R.SUPPLY_FAN_STATUS, (R.SUPPLY_FAN_CMD, R.SUPPLY_FAN_SPEED)), cmd_status,
             confirm_seconds=600, gate=GateSpec("always"), origin="open-fdd CMD-1",
             summary="The fan is commanded one way but its proven status says the other.",
             root_cause_candidates=("VFD / starter tripped", "hand-off-auto switch in hand or off",
                                    "status switch / current sensor fault", "belt broken")),
    RuleSpec("VLV-1", "Cooling valve leaking", "ahu", _AHU, (SAT, SATSP, CLG), valve_leak,
             optional=(MAT,),
             params=(Param("sat_err", 2.0 * F_DELTA, "°C", "SAT below SP by"),
                     Param("mat_leak_delta", 2.0 * F_DELTA, "°C", "SAT below MAT by")),
             confirm_seconds=900, gate=GateSpec("conditional", startup_delay_seconds=300),
             origin="open-fdd VLV-1",
             summary="Supply air is still cooled although the cooling valve is closed.",
             root_cause_candidates=_LEAK, energy_impact="chw_valve_leak"),
    RuleSpec("DMP-1", "Outdoor-air damper leaking", "ahu", _AHU, (OAT, MAT, OAD), damper_leak,
             params=(Param("leak_delta", 2.0 * F_DELTA, "°C", "MAT within this of OAT"),),
             confirm_seconds=900, gate=GateSpec("conditional", startup_delay_seconds=300),
             origin="open-fdd DMP-1",
             summary="The OA damper reads closed but mixed air tracks outdoor air.",
             root_cause_candidates=("damper blades not sealing", "actuator linkage slipped",
                                    "damper position feedback wrong"),
             energy_impact="excess_outdoor_air"),
    RuleSpec("OA-1", "Outdoor-air fraction too low", "ahu", _AHU,
             (MAT, RAT, OAT, R.SUPPLY_FAN_STATUS), oa_low,
             params=(Param("min_oa_frac", 0.15, "frac", "Minimum OA fraction"),
                     Param("oat_rat_guard", 2.2 * F_DELTA, "°C", "Minimum |RAT−OAT|")),
             confirm_seconds=900, gate=_FAN_GATE(), origin="open-fdd OA-1",
             summary="Estimated outdoor-air fraction is below the ventilation minimum.",
             root_cause_candidates=("OA damper closed or stuck", "minimum position set too low",
                                    "MAT/RAT/OAT sensor error")),
    RuleSpec("ECON-1", "Economizer stuck closed", "ahu", _AHU, (FAN_ANY, OAD, OAT), econ_stuck_closed,
             params=(Param("econ1_oat_min", f_to_c(55.0), "°C", "Favourable OAT"),),
             confirm_seconds=600, gate=_FAN_GATE(), origin="open-fdd ECON-1",
             requires_design="economizer",
             summary="The economizer stays closed while outdoor air could cool for free.",
             root_cause_candidates=("damper actuator failed", "economizer lockout wrongly enabled")),
    RuleSpec("ECON-2", "Economizing when outdoor air is unfavourable", "ahu", _AHU, (OAT, OAD),
             econ_unfavorable,
             params=(Param("econ2_oat_hi", f_to_c(63.0), "°C", "OAT high cutoff"),
                     Param("econ2_damper", 0.42, "frac", "Damper open fraction")),
             confirm_seconds=300, gate=_FAN_GATE(300), origin="open-fdd ECON-2",
             requires_design="economizer",
             summary="The OA damper is wide open while outdoor air is too warm — extra cooling load.",
             root_cause_candidates=("economizer high-limit misconfigured", "damper stuck open", "OAT sensor error"),
             energy_impact="excess_outdoor_air"),
    RuleSpec("ECON-4", "Estimated outdoor-air fraction low", "ahu", _AHU, (MAT, RAT, OAT, FAN_ANY),
             econ_low_oa,
             params=(Param("oa_min_pct", 21.0, "%", "Minimum OA percentage"),
                     Param("oat_rat_guard", 2.2 * F_DELTA, "°C", "Minimum |RAT−OAT|")),
             confirm_seconds=600, gate=_FAN_GATE(), origin="open-fdd ECON-4",
             summary="Estimated outdoor-air percentage is below the ventilation minimum.",
             root_cause_candidates=("minimum OA position too low", "damper stuck", "sensor error")),
    RuleSpec("SCHED-247", "Running around the clock", "schedule", ("ahu", "fcu", "chiller"),
             ((R.SUPPLY_FAN_STATUS, R.CHILLER_STATUS),), always_on,
             params=(Param("always_on_pct", 0.95, "frac", "Always-on fraction of the window"),),
             confirm_seconds=3600, gate=GateSpec("always"), origin="open-fdd SCHED-247",
             min_window_hours=24.0,
             summary="Equipment is proven on for nearly the entire analysis window — no schedule.",
             root_cause_candidates=("time schedule missing or overridden", "point left in hand",
                                    "zone demand never satisfied"),
             energy_impact="unscheduled_runtime"),
]
