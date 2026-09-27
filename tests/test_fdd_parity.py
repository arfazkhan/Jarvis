"""
Parity: the ARVIS port must reproduce open-fdd's confirmed faults.

The same randomized plant data (piecewise regimes + noise, so faults start and
stop around the confirmation delays) is run through both engines — ARVIS in SI
with ARVIS roles, open-fdd in imperial units with its Haystack roles — and the
confirmed fault samples must match exactly. Where ARVIS deliberately differs
(see agent_commercial/fdd/NOTICE) the oracle is given the equivalent parameter.

open-fdd is a dev-only oracle (requirements-dev-fdd.txt); tests skip without it.
"""
import numpy as np
import pandas as pd
import pytest

open_fdd_rules = pytest.importorskip("open_fdd.rules")

from agent_commercial.fdd import FDDEngine, RULES_BY_ID  # noqa: E402
from agent_commercial.fdd.frame import EquipmentFrame  # noqa: E402
from agent_commercial.fdd.rules.base import CFM_M3S, INWC_PA, PSI_PA  # noqa: E402
from agent_commercial.semantics import PointRole as R  # noqa: E402

POLL = 300.0
C2F = lambda c: c * 9.0 / 5.0 + 32.0  # noqa: E731


def _regimes(rng, n, lo, hi, p_change=0.12):
    """Piecewise-constant regimes: a new level with probability p_change per sample."""
    out, level = np.empty(n), rng.uniform(lo, hi)
    for i in range(n):
        if rng.random() < p_change:
            level = rng.uniform(lo, hi)
        out[i] = level
    return out


def _idx(hours=72):
    return pd.date_range("2026-07-01", periods=int(hours * 3600 / POLL), freq=f"{int(POLL)}s")


def ahu_data(seed: int):
    rng = np.random.default_rng(seed)
    idx = _idx()
    n = len(idx)
    on = (_regimes(rng, n, 0, 1, 0.04) > 0.2).astype(float)
    spd = np.where(on > 0, _regimes(rng, n, 0.3, 1.0), 0.0)
    oat = _regimes(rng, n, 26, 42) + rng.normal(0, 0.3, n)
    rat = _regimes(rng, n, 22, 26) + rng.normal(0, 0.2, n)
    oad = np.clip(_regimes(rng, n, -0.2, 1.1), 0, 1)
    # Mostly physical mixing, sometimes a biased MAT sensor (drives FC2/FC3/DMP-1).
    frac_oa = np.clip(oad + rng.normal(0, 0.05, n), 0, 1)
    mat = frac_oa * oat + (1 - frac_oa) * rat + _regimes(rng, n, -4, 4, 0.05)
    # Stay below open-fdd's 110 °F MAT range limit: ARVIS deliberately widens it to
    # 55 °C for Gulf 100%-OA units (pinned separately in test_fdd_engine.py).
    mat = np.minimum(mat, 43.0)
    clg = np.clip(_regimes(rng, n, -0.3, 1.1), 0, 1)
    htg = np.clip(_regimes(rng, n, -1.5, 0.6, 0.06), 0, 1)
    satsp = _regimes(rng, n, 12.5, 15.5, 0.03)
    sat = satsp + _regimes(rng, n, -4, 5) + rng.normal(0, 0.2, n)
    ccet = mat + rng.normal(0, 0.2, n)
    cclt = ccet - clg * 10 - _regimes(rng, n, -1, 3, 0.05)
    dsp_sp = np.full(n, 250.0)
    dsp = _regimes(rng, n, 120, 380) + rng.normal(0, 5, n)
    si = pd.DataFrame({
        R.SUPPLY_FAN_STATUS.value: on, R.SUPPLY_FAN_SPEED.value: spd,
        R.OUTSIDE_AIR_TEMP.value: oat, R.RETURN_AIR_TEMP.value: rat, R.MIXED_AIR_TEMP.value: mat,
        R.OUTSIDE_AIR_DAMPER.value: oad, R.COOLING_VALVE.value: clg, R.HEATING_VALVE.value: htg,
        R.SUPPLY_AIR_TEMP.value: sat, R.SUPPLY_AIR_TEMP_SP.value: satsp,
        R.COOLING_COIL_ENTERING_TEMP.value: ccet, R.COOLING_COIL_LEAVING_TEMP.value: cclt,
        R.DUCT_STATIC_PRESSURE.value: dsp, R.DUCT_STATIC_PRESSURE_SP.value: dsp_sp,
    }, index=idx)
    imp = pd.DataFrame({
        "fan-status": on, "fan-cmd": spd,
        "outside-air-temp": C2F(oat), "return-air-temp": C2F(rat), "mixed-air-temp": C2F(mat),
        "outside-air-damper": oad, "cooling-valve": clg, "heating-valve": htg,
        "discharge-air-temp": C2F(sat), "discharge-air-temp-sp": C2F(satsp),
        "cooling-coil-entering-temp": C2F(ccet), "cooling-coil-leaving-temp": C2F(cclt),
        "duct-static-pressure": dsp / INWC_PA, "duct-static-pressure-sp": dsp_sp / INWC_PA,
    }, index=idx)
    return si, imp


def ahu_stress_data(seed: int):
    """Regimes the everyday data never reaches: full heating, cold outdoor air, hot
    supply air, status independent of speed, broken/stuck sensors and a hunting valve."""
    rng = np.random.default_rng(seed)
    si, _ = ahu_data(seed)
    n = len(si)
    si[R.HEATING_VALVE.value] = np.clip(_regimes(rng, n, -0.2, 1.2), 0, 1)
    si[R.OUTSIDE_AIR_TEMP.value] = _regimes(rng, n, 2, 40) + rng.normal(0, 0.3, n)
    si[R.SUPPLY_AIR_TEMP.value] = _regimes(rng, n, 8, 34) + rng.normal(0, 0.2, n)
    si[R.SUPPLY_FAN_STATUS.value] = (_regimes(rng, n, 0, 1, 0.05) > 0.25).astype(float)
    oat = si[R.OUTSIDE_AIR_TEMP.value].to_numpy()
    rat = si[R.RETURN_AIR_TEMP.value].to_numpy()
    f = np.clip(si[R.OUTSIDE_AIR_DAMPER.value].to_numpy(), 0, 1)
    si[R.MIXED_AIR_TEMP.value] = np.minimum(f * oat + (1 - f) * rat + _regimes(rng, n, -3, 3, 0.05), 43.0)
    sat = si[R.SUPPLY_AIR_TEMP.value].to_numpy()
    sat[100:112] = 90.0                                    # out of physical range (SV-RANGE)
    si[R.SUPPLY_AIR_TEMP.value] = sat
    rat = si[R.RETURN_AIR_TEMP.value].to_numpy()
    rat[300:340] = 23.4                                    # frozen sensor (SV-FLATLINE)
    si[R.RETURN_AIR_TEMP.value] = rat
    clg = si[R.COOLING_VALVE.value].to_numpy()
    t = np.arange(n)
    hunt = slice(500, 540)                                 # 10-min square wave (PID-HUNT-1)
    clg[hunt] = np.where((t[hunt] // 2) % 2 == 0, 0.1, 0.9)
    si[R.COOLING_VALVE.value] = clg
    si.iloc[hunt, si.columns.get_loc(R.SUPPLY_FAN_STATUS.value)] = 1.0
    si.iloc[hunt, si.columns.get_loc(R.SUPPLY_FAN_SPEED.value)] = 0.8
    imp = pd.DataFrame({
        "fan-status": si[R.SUPPLY_FAN_STATUS.value], "fan-cmd": si[R.SUPPLY_FAN_SPEED.value],
        "outside-air-temp": C2F(si[R.OUTSIDE_AIR_TEMP.value]),
        "return-air-temp": C2F(si[R.RETURN_AIR_TEMP.value]),
        "mixed-air-temp": C2F(si[R.MIXED_AIR_TEMP.value]),
        "outside-air-damper": si[R.OUTSIDE_AIR_DAMPER.value],
        "cooling-valve": si[R.COOLING_VALVE.value], "heating-valve": si[R.HEATING_VALVE.value],
        "discharge-air-temp": C2F(si[R.SUPPLY_AIR_TEMP.value]),
        "discharge-air-temp-sp": C2F(si[R.SUPPLY_AIR_TEMP_SP.value]),
        "cooling-coil-entering-temp": C2F(si[R.COOLING_COIL_ENTERING_TEMP.value]),
        "cooling-coil-leaving-temp": C2F(si[R.COOLING_COIL_LEAVING_TEMP.value]),
        "duct-static-pressure": si[R.DUCT_STATIC_PRESSURE.value] / INWC_PA,
        "duct-static-pressure-sp": si[R.DUCT_STATIC_PRESSURE_SP.value] / INWC_PA,
    }, index=si.index)
    return si, imp


def vav_data(seed: int):
    rng = np.random.default_rng(seed)
    idx = _idx()
    n = len(idx)
    flow_cfm = np.clip(_regimes(rng, n, -100, 900), 0, None)
    dmp = np.clip(_regimes(rng, n, -0.2, 1.1), 0, 1)
    zt = _regimes(rng, n, 20, 26) + rng.normal(0, 0.15, n)
    rhv = np.clip(_regimes(rng, n, -1, 1, 0.06), 0, 1)
    inlet = _regimes(rng, n, 12, 16, 0.05)
    dat = inlet + rhv * _regimes(rng, n, 0, 12, 0.08)
    oat = _regimes(rng, n, 16, 40)
    si = pd.DataFrame({
        R.TERMINAL_AIRFLOW.value: flow_cfm * CFM_M3S, R.TERMINAL_DAMPER.value: dmp,
        R.ZONE_TEMP.value: zt, R.REHEAT_VALVE.value: rhv, R.TERMINAL_INLET_TEMP.value: inlet,
        R.TERMINAL_DISCHARGE_TEMP.value: dat, R.OUTSIDE_AIR_TEMP.value: oat,
    }, index=idx)
    imp = pd.DataFrame({
        "zone-airflow": flow_cfm, "damper": dmp, "zone-air-temp": C2F(zt), "reheat-valve": rhv,
        "vav-inlet-air-temp": C2F(inlet), "vav-discharge-air-temp": C2F(dat),
        "outside-air-temp": C2F(oat),
    }, index=idx)
    return si, imp


def chw_data(seed: int):
    rng = np.random.default_rng(seed)
    idx = _idx()
    n = len(idx)
    status = (_regimes(rng, n, 0, 1, 0.04) > 0.2).astype(float)
    pump = np.where(status > 0, _regimes(rng, n, 0.4, 1.0), 0.0)
    chws = _regimes(rng, n, 5.0, 9.5) + rng.normal(0, 0.1, n)
    sp = np.full(n, 6.7)
    chwr = chws + _regimes(rng, n, 0.5, 6.5) + rng.normal(0, 0.1, n)
    dp_sp = np.full(n, 70000.0)
    dp = _regimes(rng, n, 30000, 95000)
    si = pd.DataFrame({
        R.CHILLER_STATUS.value: status, R.PUMP_SPEED.value: pump, R.CHW_SUPPLY_TEMP.value: chws,
        R.CHW_SUPPLY_TEMP_SP.value: sp, R.CHW_RETURN_TEMP.value: chwr,
        R.CHW_DP.value: dp, R.CHW_DP_SP.value: dp_sp,
    }, index=idx)
    imp = pd.DataFrame({
        "chiller-status": status, "chw-pump-cmd": pump, "chilled-water-supply-temp": C2F(chws),
        "chilled-water-supply-temp-sp": C2F(sp), "chilled-water-return-temp": C2F(chwr),
        "chw-diff-pressure": dp / PSI_PA, "chw-diff-pressure-sp": dp_sp / PSI_PA,
    }, index=idx)
    return si, imp


def _ours(rule_id, si, kind, eq_id, design=None):
    """Full ARVIS pipeline for one rule. open-fdd blanks out-of-range samples in a
    quality layer before its rules run; ARVIS does that through the SV-RANGE sweep,
    so SV-RANGE is the (only) invalidation source here. ARVIS also invalidates on
    SV-FLATLINE / SV-SPIKE, which open-fdd does not — that is excluded from parity."""
    ef = EquipmentFrame(eq_id, kind, si, points_used={c: f"{eq_id}/{c}" for c in si.columns},
                        design_attributes=design or {})
    rules = [RULES_BY_ID[rule_id]]
    if rule_id != "SV-RANGE":
        rules.insert(0, RULES_BY_ID["SV-RANGE"])
    eng = FDDEngine(rules, poll_seconds=POLL)
    return next(f for f in eng.evaluate(ef) if f.rule_id == rule_id)


def _theirs(rule_id, imp, eq_id, eq_type, extra=None):
    df = imp.copy()
    df.attrs["equipment_id"] = eq_id
    df.attrs["equipment_type"] = eq_type
    rule = RULES_BY_ID[rule_id]
    params = {"confirm_min": rule.confirm_seconds / 60.0, **(extra or {})}
    return open_fdd_rules.run_rule(rule_id, df, params=params, poll_seconds=POLL)


def _compare(ours, theirs):
    status = {"FAULT": "fail", "PASS": "pass"}.get(theirs.status, "skip")
    assert ours.outcome.value == status, (ours.reason, theirs.status, theirs.notes)
    if status != "skip":
        assert ours.fault_sample_count == theirs.fault_sample_count, (
            ours.fault_sample_count, theirs.fault_sample_count)
        if theirs.fault_sample_count:
            idx = theirs.confirmed_fault.index[theirs.confirmed_fault]
            assert ours.first_fault == str(idx[0]) and ours.last_fault == str(idx[-1])


AHU_RULES = ["FC2", "FC3", "FC5", "FC7", "FC8", "FC9", "FC10", "FC11", "FC12", "FC13", "FC14",
             "AHU-SATDEV", "AHU-DUCTHI", "AHU-SIMUL", "CMD-1", "VLV-1", "DMP-1", "OA-1",
             "ECON-1", "ECON-2", "ECON-4", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "PID-HUNT-1"]
# ARVIS FC13 uses the GL36 full-cooling threshold; give the oracle the same.
ORACLE_PARAMS = {"FC13": {"clg_full_min": 0.95}, "PID-HUNT-1": {"confirm_min": 0.0}}


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("rule_id", AHU_RULES)
def test_ahu_parity(rule_id, seed):
    si, imp = ahu_data(seed)
    ours = _ours(rule_id, si, "ahu", "AHU-1", design={"economizer": True})
    theirs = _theirs(rule_id, imp, "AHU-1", "AHU", ORACLE_PARAMS.get(rule_id))
    _compare(ours, theirs)


STRESS_RULES = ["FC5", "FC7", "FC11", "FC12", "CMD-1", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE",
                "PID-HUNT-1", "AHU-SATDEV", "VLV-1", "FC13"]


@pytest.mark.parametrize("seed", [11, 12, 13])
@pytest.mark.parametrize("rule_id", STRESS_RULES)
def test_ahu_stress_parity(rule_id, seed):
    si, imp = ahu_stress_data(seed)
    ours = _ours(rule_id, si, "ahu", "AHU-1", design={"economizer": True})
    theirs = _theirs(rule_id, imp, "AHU-1", "AHU", ORACLE_PARAMS.get(rule_id))
    _compare(ours, theirs)


def test_stress_data_actually_faults():
    """Guard: parity on all-PASS data proves nothing — each stress rule must fault
    on at least one seed."""
    for rule_id in STRESS_RULES:
        counts = []
        for seed in (11, 12, 13):
            si, _ = ahu_stress_data(seed)
            counts.append(_ours(rule_id, si, "ahu", "AHU-1", design={"economizer": True}).fault_sample_count)
        assert max(counts) > 0, f"{rule_id} never faulted on stress data {counts}"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fc1_parity_speed_only(seed):
    """FC1: ARVIS requires the VFD speed signal; compare on a frame without fan status
    (with status, open-fdd reduces 'fan at full speed' to 'fan running')."""
    si, imp = ahu_data(seed)
    si = si.drop(columns=[R.SUPPLY_FAN_STATUS.value])
    imp = imp.drop(columns=["fan-status"])
    _compare(_ours("FC1", si, "ahu", "AHU-1"), _theirs("FC1", imp, "AHU-1", "AHU"))


@pytest.mark.parametrize("seed", [4, 5, 6])
@pytest.mark.parametrize("rule_id", ["VAV-1", "VAV-3", "VAV-4", "VAV-5", "VAV-6", "VAV-REHEAT",
                                     "SV-RANGE", "SV-SPIKE"])
def test_vav_parity(rule_id, seed):
    si, imp = vav_data(seed)
    _compare(_ours(rule_id, si, "vav", "VAV-1"), _theirs(rule_id, imp, "VAV-1", "VAV"))


@pytest.mark.parametrize("seed", [7, 8, 9])
@pytest.mark.parametrize("rule_id", ["CHW-1", "CHW-2", "CHW-3", "SV-RANGE", "SV-SPIKE"])
def test_chw_parity(rule_id, seed):
    si, imp = chw_data(seed)
    _compare(_ours(rule_id, si, "chiller", "CH-1"), _theirs(rule_id, imp, "CH-1", "CHILLER"))
