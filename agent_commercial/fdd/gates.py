"""
Operational gates — "was the equipment running, so the rule is fair to judge?"

Ported from open-fdd's operational_gate (MIT — see NOTICE) with one deliberate
difference: when a mechanical rule has no run-proof point at all, open-fdd
treats every sample as running; ARVIS SKIPs the rule ("cannot tell whether the
unit was on") unless the site opts in with ``allow_ungated``. A fault raised
while the unit was simply off is a fabricated fault.

Sensor-validation sweeps are the exception: an impossible reading is wrong
whether or not the equipment runs, so they may evaluate ungated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import pandas as pd

from agent_commercial.fdd.timeseries import apply_startup_delay
from agent_commercial.semantics import PointRole as R

# Airflow above which a VAV/FCU box is taken to be receiving air (50 cfm).
AIR_ON_M3S = 0.0236
# Plant flow above which a hydronic loop is taken to be flowing.
FLOW_ON_LS = 0.1


@dataclass(frozen=True)
class GateSpec:
    kind: str = "always"        # always | fan_running | hydronic_flow | conditional |
                                # equipment_energized | control_loop
    startup_delay_seconds: float = 0.0
    minimum_active_coverage_pct: float = 5.0
    ungated_ok: bool = False    # True only for sensor sweeps


def _col(d: pd.DataFrame, role: R) -> Optional[pd.Series]:
    c = role.value
    if c in d.columns and d[c].notna().any():
        return pd.to_numeric(d[c], errors="coerce")
    return None


def _on(series: pd.Series, threshold: float) -> pd.Series:
    return series.fillna(0) > threshold


def resolve_fan_running(d: pd.DataFrame) -> Tuple[Optional[pd.Series], str]:
    """Proof first (status, speed), command as fallback, box airflow as a proxy."""
    for role, thr in ((R.SUPPLY_FAN_STATUS, 0.5), (R.SUPPLY_FAN_SPEED, 0.05)):
        s = _col(d, role)
        if s is not None:
            return _on(s, thr), role.value
    s = _col(d, R.SUPPLY_FAN_CMD)
    if s is not None:
        return _on(s, 0.5), f"{R.SUPPLY_FAN_CMD.value} (cmd fallback)"
    s = _col(d, R.TERMINAL_AIRFLOW)
    if s is not None:
        return _on(s, AIR_ON_M3S), R.TERMINAL_AIRFLOW.value
    return None, "no_run_proof"


def resolve_hydronic_running(d: pd.DataFrame) -> Tuple[Optional[pd.Series], str]:
    for role, thr in ((R.CHILLER_STATUS, 0.5), (R.PUMP_SPEED, 0.05),
                      (R.CHW_FLOW, FLOW_ON_LS), (R.DC_PRIMARY_FLOW, FLOW_ON_LS)):
        s = _col(d, role)
        if s is not None:
            return _on(s, thr), role.value
    return None, "no_run_proof"


def resolve_equipment_energized(d: pd.DataFrame) -> Tuple[Optional[pd.Series], str]:
    fan, src = resolve_fan_running(d)
    if fan is not None:
        return fan, src
    return resolve_hydronic_running(d)


def resolve_conditional(d: pd.DataFrame, rule_id: str, params: Dict) -> Tuple[Optional[pd.Series], str]:
    if rule_id in ("VAV-1",):
        occ = _col(d, R.OCCUPANCY)
        fan, src = resolve_fan_running(d)
        if occ is not None:
            occ_on = _on(occ, 0.5)
            return ((occ_on & fan) if fan is not None else occ_on), (
                f"occupancy_and_{src}" if fan is not None else R.OCCUPANCY.value)
        return fan, src
    if rule_id == "DMP-1":
        fan, src = resolve_fan_running(d)
        dmp = _col(d, R.OUTSIDE_AIR_DAMPER)
        if dmp is not None:
            cmd = _on(dmp, 0.01)
            return ((fan | cmd) if fan is not None else cmd), f"damper_or_{src}"
        return fan, src
    if rule_id == "AHU-DUCTHI":
        fan, src = resolve_fan_running(d)
        dsp = _col(d, R.DUCT_STATIC_PRESSURE)
        thr = float(params.get("pressure_on_min", 49.8))
        if dsp is not None:
            press = dsp.abs().fillna(0) > thr
            return ((fan | press) if fan is not None else press), f"fan_or_duct_static:{src}"
        return fan, src
    if rule_id == "SV-FLATLINE":
        return resolve_equipment_energized(d)
    # VLV-1 and any other conditional rule: fan proof.
    return resolve_fan_running(d)


def resolve_active_mask(d: pd.DataFrame, rule_id: str, gate: GateSpec, *,
                        poll_seconds: float, params: Dict,
                        allow_ungated: bool = False) -> Tuple[Optional[pd.Series], Dict]:
    """Return (active_mask or None, meta). None means the rule must be SKIPPED
    (meta['skip_reason'] says why)."""
    meta: Dict = {"gate_kind": gate.kind, "gate_source": "always"}
    if gate.kind == "always":
        return pd.Series(True, index=d.index), meta

    if gate.kind == "fan_running" or gate.kind == "control_loop":
        active, src = resolve_fan_running(d)
    elif gate.kind == "hydronic_flow":
        active, src = resolve_hydronic_running(d)
    elif gate.kind == "equipment_energized":
        active, src = resolve_equipment_energized(d)
    elif gate.kind == "conditional":
        active, src = resolve_conditional(d, rule_id, params)
    else:
        active, src = pd.Series(True, index=d.index), "always"
    meta["gate_source"] = src

    if active is None:
        if gate.ungated_ok or allow_ungated:
            meta["gate_source"] = "ungated_no_run_proof"
            return pd.Series(True, index=d.index), meta
        meta["skip_reason"] = ("no run-proof point mapped (fan/pump/chiller status, speed "
                               "or flow) — cannot tell whether the equipment was running")
        return None, meta

    delay = float(params.get("startup_delay_s", gate.startup_delay_seconds))
    active = apply_startup_delay(active, poll_seconds, delay)
    n_active = int(active.sum())
    coverage = 100.0 * n_active / max(len(d), 1)
    meta.update({"startup_delay_s": delay, "active_sample_count": n_active,
                 "active_coverage_pct": round(coverage, 1)})
    if n_active == 0 or coverage < gate.minimum_active_coverage_pct:
        meta["skip_reason"] = (f"equipment not proven running in this window "
                               f"({coverage:.0f}% of samples via {src})")
        return None, meta
    return active, meta
