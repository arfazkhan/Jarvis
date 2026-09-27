"""
Sensor validation + control-loop hunting (ported from open-fdd, MIT — see NOTICE).

These run first. Their per-role confirmed masks mark samples of a sensor as
untrustworthy, and the engine then treats any mechanical rule that depends on
that sensor as INVALID for those samples instead of raising a fault from a
broken sensor.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from agent_commercial.fdd.gates import GateSpec
from agent_commercial.fdd.rules.base import (
    F_DELTA, INWC_PA, Param, RuleContext, RuleSpec, col, f_to_c, false, has, p,
)
from agent_commercial.fdd.timeseries import flatline_mask
from agent_commercial.semantics import PointRole as R

# (lo, hi, spike-per-sample) in SI, converted from open-fdd's imperial limits.
# One Gulf change: mixed-air high limit raised from 110 °F (43.3 °C) to 55 °C,
# because 100%-outdoor-air units see mixed air ≈ outdoor air (≈50 °C in summer).
SENSOR_LIMITS: Dict[R, tuple] = {
    R.OUTSIDE_AIR_TEMP: (f_to_c(-60), f_to_c(130), 36 * F_DELTA),
    R.RETURN_AIR_TEMP: (f_to_c(40), f_to_c(100), 12 * F_DELTA),
    R.MIXED_AIR_TEMP: (f_to_c(-20), 55.0, 25 * F_DELTA),
    R.SUPPLY_AIR_TEMP: (f_to_c(30), f_to_c(150), 40 * F_DELTA),
    R.TERMINAL_DISCHARGE_TEMP: (f_to_c(30), f_to_c(150), 40 * F_DELTA),
    R.ZONE_TEMP: (f_to_c(40), f_to_c(100), 12 * F_DELTA),
    R.CHW_SUPPLY_TEMP: (f_to_c(30), f_to_c(80), 20 * F_DELTA),
    R.CHW_RETURN_TEMP: (f_to_c(30), f_to_c(90), 20 * F_DELTA),
    R.DC_PRIMARY_SUPPLY_TEMP: (f_to_c(30), f_to_c(80), 20 * F_DELTA),
    R.DC_PRIMARY_RETURN_TEMP: (f_to_c(30), f_to_c(90), 20 * F_DELTA),
    R.ZONE_HUMIDITY: (0.0, 100.0, 25.0),
    R.DUCT_STATIC_PRESSURE: (-1.0 * INWC_PA, 8.0 * INWC_PA, 2.0 * INWC_PA),
}
SWEEP_ROLES = list(SENSOR_LIMITS)
# Pressure legitimately rests near zero when the fan is off — not a stuck sensor.
FLATLINE_ROLES = [r for r in SWEEP_ROLES if r is not R.DUCT_STATIC_PRESSURE]
_FLAT_TOL = {R.ZONE_HUMIDITY: 0.10}          # %RH; temperatures use flatline_tol (°C)

# Analog 0–1 control outputs checked for hunting.
CONTROL_OUTPUT_ROLES = [
    R.OUTSIDE_AIR_DAMPER, R.COOLING_VALVE, R.HEATING_VALVE, R.TERMINAL_DAMPER,
    R.REHEAT_VALVE, R.SUPPLY_FAN_SPEED, R.PUMP_SPEED, R.COOLING_TOWER_FAN_SPEED,
]


def _publish(ctx: RuleContext, per_role: Dict[R, pd.Series]) -> None:
    ctx.per_role_masks = {r.value: m.fillna(False).astype(bool) for r, m in per_role.items()}


def _window(hours: float, poll: float) -> int:
    return max(2, int(round(hours * 3600 / max(poll, 1))))


def sv_range(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    mask, per_role = false(d), {}
    for role in SWEEP_ROLES:
        if role.value not in d.columns:
            continue
        s = col(d, role)
        lo, hi, _ = SENSOR_LIMITS[role]
        mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0 * max(p(prm, "range_scale"), 1e-6)
        m = s.notna() & ((s < mid - half) | (s > mid + half))
        per_role[role] = m
        mask = mask | m
    _publish(ctx, per_role)
    return mask


def sv_flatline(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    window = _window(p(prm, "flatline_hours"), ctx.poll_seconds)
    mask, per_role = false(d), {}
    for role in FLATLINE_ROLES:
        if role.value not in d.columns:
            continue
        m = flatline_mask(col(d, role), tol=_FLAT_TOL.get(role, p(prm, "flatline_tol")), window=window)
        per_role[role] = m
        mask = mask | m
    _publish(ctx, per_role)
    return mask


def sv_spike(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    mask, per_role = false(d), {}
    for role in SWEEP_ROLES:
        if role.value not in d.columns:
            continue
        s = col(d, role)
        m = s.notna() & (s.diff().abs() > SENSOR_LIMITS[role][2] * p(prm, "spike_scale"))
        per_role[role] = m
        mask = mask | m
    _publish(ctx, per_role)
    return mask


def sv_stale(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    """All mapped sensors unchanged across the window → the data feed has died."""
    present = [r for r in FLATLINE_ROLES if r.value in d.columns]
    if not present:
        _publish(ctx, {})
        return false(d)
    window = _window(p(prm, "stale_hours"), ctx.poll_seconds)
    stale = pd.Series(True, index=d.index)
    for role in present:
        stale = stale & flatline_mask(col(d, role), tol=1e-9, window=window)
    _publish(ctx, {role: stale.copy() for role in present})
    return stale


def hunting_fault_mask(output_pct: pd.Series, *, poll_seconds: float, prm: Dict) -> pd.Series:
    """Rolling 1-hour hunting test on a 0–100 % output (open-fdd PID-HUNT-1)."""
    output = output_pct.clip(lower=0.0, upper=100.0).sort_index()
    interval = pd.Timedelta(seconds=float(poll_seconds))
    window = pd.Timedelta("1h")
    expected = max(2, int(window / interval))
    min_samples = max(2, int(np.ceil(expected * p(prm, "minimum_coverage_pct") / 100.0)))

    delta = output.diff()
    sig = delta.where(delta.abs() >= p(prm, "change_deadband_pct"), 0.0)
    tv = sig.abs().rolling(window, min_periods=min_samples).sum()
    span = (output.rolling(window, min_periods=min_samples).max()
            - output.rolling(window, min_periods=min_samples).min())
    direction = pd.Series(np.sign(sig.to_numpy(dtype="float64")), index=sig.index).replace(0.0, np.nan)
    prev = direction.ffill().shift(1)
    reversal = (direction.notna() & prev.notna() & direction.ne(prev)).astype("int64")
    reversals = reversal.rolling(window, min_periods=min_samples).sum()
    coverage = (100.0 * output.notna().astype("int64").rolling(window, min_periods=1).sum()
                / float(expected)).clip(upper=100.0)
    cycles = tv / (2.0 * span.replace(0.0, np.nan))
    return (coverage.ge(p(prm, "minimum_coverage_pct"))
            & span.ge(p(prm, "minimum_span_pct"))
            & tv.ge(p(prm, "total_variation_fault_pct"))
            & cycles.ge(p(prm, "minimum_equivalent_cycles"))
            & reversals.ge(p(prm, "minimum_reversals"))).fillna(False)


def pid_hunt(d: pd.DataFrame, prm: Dict, ctx: RuleContext) -> pd.Series:
    mask, per_role = false(d), {}
    for role in CONTROL_OUTPUT_ROLES:
        if not has(d, role):
            continue
        m = hunting_fault_mask(col(d, role) * 100.0, poll_seconds=ctx.poll_seconds,
                               prm=prm).reindex(d.index).fillna(False)
        per_role[role] = m
        mask = mask | m
    ctx.notes["outputs_checked"] = [r.value for r in per_role]
    ctx.notes["hunting_outputs"] = [r.value for r, m in per_role.items() if bool(m.any())]
    return mask


_SENSOR_KINDS = ("ahu", "vav", "fcu", "chiller", "plant", "pump", "cooling_tower", "other")
_SWEEP_GATE = GateSpec("equipment_energized", ungated_ok=True)

RULES = [
    RuleSpec(
        "SV-RANGE", "Sensor out of physical range", "sensor", _SENSOR_KINDS, (), sv_range,
        params=(Param("range_scale", 1.0, "x", "Range scale (>1 widens limits)"),),
        confirm_seconds=300, gate=_SWEEP_GATE, sensor_sweep=True, origin="open-fdd SV-RANGE",
        summary="A sensor reads outside its physically possible range.",
        root_cause_candidates=("failed sensor", "wiring / open circuit", "wrong unit or scaling in BMS"),
    ),
    RuleSpec(
        "SV-FLATLINE", "Sensor stuck (flatline)", "sensor", _SENSOR_KINDS, (), sv_flatline,
        params=(Param("flatline_tol", 0.10 * F_DELTA, "°C", "Flatline tolerance"),
                Param("flatline_hours", 1.0, "h", "Flatline window")),
        confirm_seconds=300, gate=GateSpec("conditional", ungated_ok=True), sensor_sweep=True,
        origin="open-fdd SV-FLATLINE",
        summary="A sensor stays within a tiny band for too long — stuck or frozen.",
        root_cause_candidates=("stuck / failed sensor", "BMS point overridden or out of service",
                               "controller not updating the value"),
    ),
    RuleSpec(
        "SV-SPIKE", "Sensor spike", "sensor", _SENSOR_KINDS, (), sv_spike,
        params=(Param("spike_scale", 1.0, "x", "Spike limit scale"),),
        confirm_seconds=300, gate=_SWEEP_GATE, sensor_sweep=True, origin="open-fdd SV-SPIKE",
        summary="A sensor jumps between samples by more than is physically plausible.",
        root_cause_candidates=("intermittent wiring", "electrical noise", "failing sensor"),
    ),
    RuleSpec(
        "SV-STALE", "Data feed stale", "sensor", _SENSOR_KINDS, (), sv_stale,
        params=(Param("stale_hours", 2.0, "h", "Stale window"),),
        confirm_seconds=300, gate=GateSpec("always"), sensor_sweep=True, origin="open-fdd SV-STALE",
        summary="Every mapped sensor on the equipment stopped changing — the data feed likely dropped.",
        root_cause_candidates=("controller offline", "BMS integration / network outage",
                               "BACnet device not responding"),
    ),
    RuleSpec(
        "PID-HUNT-1", "Control loop hunting", "control",
        ("ahu", "vav", "fcu", "chiller", "plant", "pump", "cooling_tower"), (), pid_hunt,
        params=(Param("change_deadband_pct", 1.0, "%", "Ignore changes below"),
                Param("minimum_span_pct", 20.0, "%", "Minimum observed span"),
                Param("total_variation_fault_pct", 500.0, "%/h", "Total travel threshold"),
                Param("minimum_equivalent_cycles", 2.5, "cyc/h", "Minimum equivalent cycles"),
                Param("minimum_reversals", 4.0, "count", "Minimum direction reversals"),
                Param("minimum_coverage_pct", 80.0, "%", "Minimum data coverage")),
        confirm_seconds=0, gate=GateSpec("control_loop", startup_delay_seconds=300),
        origin="open-fdd PID-HUNT-1",
        summary="A valve, damper or speed output oscillates enough to suggest a hunting control loop.",
        root_cause_candidates=("PID gains too aggressive", "oversized valve / actuator",
                               "sensor lag or poor sensor location", "interacting control loops"),
        energy_impact="hunting",
    ),
]
