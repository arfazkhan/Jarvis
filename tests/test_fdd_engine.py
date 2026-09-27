"""ARVIS FDD engine — the grounding behaviours that go beyond the open-fdd port."""
import asyncio
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from agent_commercial.fdd import FDDEngine, Outcome, RULES_BY_ID, enrich_context
from agent_commercial.fdd.frame import EquipmentFrame, build_frame
from agent_commercial.semantics import PointRole as R, PointRoleRegistry

POLL = 300.0


def _idx(hours=24):
    return pd.date_range("2026-07-01", periods=int(hours * 12), freq="300s")


def _ef(cols, kind="ahu", eq="AHU-1", design=None, parent=None):
    idx = _idx()
    df = pd.DataFrame({k.value if isinstance(k, R) else k:
                       (v if hasattr(v, "__len__") else np.full(len(idx), float(v)))
                       for k, v in cols.items()}, index=idx)
    return EquipmentFrame(eq, kind, df, points_used={c: f"{eq}/{c}" for c in df.columns},
                          design_attributes=design or {}, parent_id=parent)


def _run(rule_ids, ef, **kw):
    eng = FDDEngine([RULES_BY_ID[r] for r in rule_ids], poll_seconds=POLL, **kw)
    return {f.rule_id: f for f in eng.evaluate(ef)}


def test_no_run_proof_skips_instead_of_assuming_running():
    ef = _ef({R.SUPPLY_AIR_TEMP: 25.0, R.SUPPLY_AIR_TEMP_SP: 14.0})
    f = _run(["AHU-SATDEV"], ef)["AHU-SATDEV"]
    assert f.outcome is Outcome.SKIP and "cannot tell whether the equipment was running" in f.reason
    # A site may explicitly opt in to open-fdd's behaviour.
    f = _run(["AHU-SATDEV"], ef, allow_ungated=True)["AHU-SATDEV"]
    assert f.outcome is Outcome.FAIL and f.gate_source == "ungated_no_run_proof"


def test_failed_sensor_makes_rule_invalid_not_a_fault():
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.SUPPLY_AIR_TEMP: 95.0, R.SUPPLY_AIR_TEMP_SP: 14.0})
    out = _run(["SV-RANGE", "AHU-SATDEV"], ef)
    assert out["SV-RANGE"].outcome is Outcome.FAIL
    assert out["SV-RANGE"].invalid_roles == [R.SUPPLY_AIR_TEMP.value]
    assert out["AHU-SATDEV"].outcome is Outcome.INVALID
    assert R.SUPPLY_AIR_TEMP.value in out["AHU-SATDEV"].invalid_roles


def test_stuck_sensor_also_invalidates_dependents():
    """Stricter than open-fdd, whose quality layer only drops out-of-range samples."""
    n = len(_idx())
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.MIXED_AIR_TEMP: 10.0 + np.random.default_rng(1).normal(0, .3, n),
              R.OUTSIDE_AIR_TEMP: 35.0 + np.random.default_rng(2).normal(0, .3, n),
              R.RETURN_AIR_TEMP: 24.0})                     # frozen RAT
    out = _run(["SV-FLATLINE", "FC2"], ef)
    assert R.RETURN_AIR_TEMP.value in out["SV-FLATLINE"].invalid_roles
    assert out["FC2"].outcome is Outcome.INVALID


def test_site_parameter_required_rules_skip_until_configured():
    ef = _ef({R.CHILLER_STATUS: 1.0, R.PUMP_SPEED: 0.95, R.CHW_FLOW: 90.0}, kind="plant", eq="CHW-PLANT")
    f = _run(["CHW-4"], ef)["CHW-4"]
    assert f.outcome is Outcome.SKIP and "flow_hi" in f.reason
    f = _run(["CHW-4"], ef, params_by_rule={"CHW-4": {"flow_hi": 60.0}})["CHW-4"]
    assert f.outcome is Outcome.FAIL


def test_economizer_rules_need_declared_economizer():
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.SUPPLY_AIR_TEMP: 20.0, R.MIXED_AIR_TEMP: 12.0,
              R.OUTSIDE_AIR_DAMPER: 0.8, R.COOLING_VALVE: 0.0})
    assert _run(["FC8"], ef)["FC8"].outcome is Outcome.SKIP
    ef.design_attributes = {"economizer": False}
    assert "declared False" in _run(["FC8"], ef)["FC8"].reason
    ef.design_attributes = {"economizer": True}
    assert _run(["FC8"], ef)["FC8"].outcome is Outcome.FAIL


def test_fc14_catches_passing_chw_valve_on_fahu_without_damper():
    leak = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.COOLING_VALVE: 0.0,
                R.COOLING_COIL_ENTERING_TEMP: 44.0, R.COOLING_COIL_LEAVING_TEMP: 40.0})
    assert _run(["FC14"], leak)["FC14"].outcome is Outcome.FAIL
    tight = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.COOLING_VALVE: 0.0,
                 R.COOLING_COIL_ENTERING_TEMP: 44.0, R.COOLING_COIL_LEAVING_TEMP: 43.9})
    assert _run(["FC14"], tight)["FC14"].outcome is Outcome.PASS
    cooling = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.COOLING_VALVE: 0.8,
                   R.COOLING_COIL_ENTERING_TEMP: 44.0, R.COOLING_COIL_LEAVING_TEMP: 14.0})
    assert _run(["FC14"], cooling)["FC14"].outcome is Outcome.PASS


def test_hot_mixed_air_is_not_a_sensor_fault_in_the_gulf():
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.MIXED_AIR_TEMP: 48.0})
    assert _run(["SV-RANGE"], ef)["SV-RANGE"].outcome is Outcome.PASS


def test_single_sample_blip_is_not_confirmed():
    sat = np.full(len(_idx()), 14.0)
    sat[50] = 25.0
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.SUPPLY_AIR_TEMP: sat, R.SUPPLY_AIR_TEMP_SP: 14.0})
    assert _run(["AHU-SATDEV"], ef)["AHU-SATDEV"].outcome is Outcome.PASS
    sat[50:60] = 25.0                                        # 50 minutes → confirmed
    ef = _ef({R.SUPPLY_FAN_STATUS: 1.0, R.SUPPLY_AIR_TEMP: sat, R.SUPPLY_AIR_TEMP_SP: 14.0})
    f = _run(["AHU-SATDEV"], ef)["AHU-SATDEV"]
    assert f.outcome is Outcome.FAIL and 0 < f.fault_hours < 1.0


def test_chiller_running_with_no_building_demand():
    frames = {
        "CH-1": _ef({R.CHILLER_STATUS: 1.0}, kind="chiller", eq="CH-1"),
        "AHU-1": _ef({R.COOLING_VALVE: 0.0}, eq="AHU-1"),
        "AHU-2": _ef({R.COOLING_VALVE: 0.02}, eq="AHU-2"),
    }
    enrich_context(frames)
    assert _run(["CHW-NOLOAD-1"], frames["CH-1"])["CHW-NOLOAD-1"].outcome is Outcome.FAIL
    frames["AHU-2"] = _ef({R.COOLING_VALVE: 0.6}, eq="AHU-2")
    frames["CH-1"] = _ef({R.CHILLER_STATUS: 1.0}, kind="chiller", eq="CH-1")
    enrich_context(frames)
    assert _run(["CHW-NOLOAD-1"], frames["CH-1"])["CHW-NOLOAD-1"].outcome is Outcome.PASS


def test_vav_compared_with_parent_ahu_supply_air():
    frames = {
        "AHU-1": _ef({R.SUPPLY_AIR_TEMP: 13.0}, eq="AHU-1"),
        "VAV-1": _ef({R.TERMINAL_AIRFLOW: 0.2, R.TERMINAL_DISCHARGE_TEMP: 22.0}, kind="vav",
                     eq="VAV-1", parent="AHU-1"),
    }
    enrich_context(frames)
    f = _run(["VAV-AHU-LEAVE"], frames["VAV-1"])["VAV-AHU-LEAVE"]
    assert f.outcome is Outcome.FAIL
    assert f.role_sources["ctx:parent-supply-air-temp"] == "context"


def test_always_on_needs_a_full_day_of_data():
    short = EquipmentFrame("AHU-1", "ahu", pd.DataFrame(
        {R.SUPPLY_FAN_STATUS.value: 1.0}, index=pd.date_range("2026-07-01", periods=72, freq="300s")))
    f = _run(["SCHED-247"], short)["SCHED-247"]
    assert f.outcome is Outcome.SKIP and "needs ≥24 h" in f.reason
    long = EquipmentFrame("AHU-1", "ahu", pd.DataFrame(
        {R.SUPPLY_FAN_STATUS.value: 1.0}, index=pd.date_range("2026-07-01", periods=300, freq="300s")))
    assert _run(["SCHED-247"], long)["SCHED-247"].outcome is Outcome.FAIL


def test_district_cooling_dt_against_contract():
    ef = _ef({R.DC_PRIMARY_FLOW: 40.0, R.DC_PRIMARY_SUPPLY_TEMP: 5.5,
              R.DC_PRIMARY_RETURN_TEMP: 11.0}, kind="plant", eq="ETS-1")
    assert _run(["DC-DT-1"], ef)["DC-DT-1"].outcome is Outcome.SKIP        # contract unknown
    f = _run(["DC-DT-1"], ef, params_by_rule={"DC-DT-1": {"contract_min_dt": 8.0}})["DC-DT-1"]
    assert f.outcome is Outcome.FAIL


# ── frames from stored telemetry ──────────────────────────────────────────────

def _rows(pid, unit, values, start=datetime(2026, 7, 1)):
    return [{"point_id": pid, "unit": unit, "value": v,
             "timestamp": (start + timedelta(minutes=5 * i)).isoformat()} for i, v in enumerate(values)]


def test_frame_converts_site_units_and_uses_only_trusted_roles():
    reg = PointRoleRegistry()
    rows = (_rows("AHU-1/SAT", "degreesFahrenheit", [59.0] * 12)
            + _rows("AHU-1/DSP", "inchesOfWater", [1.0] * 12)
            + _rows("AHU-1/OAT", "furlongs", [1.0] * 12)          # unconvertible
            + _rows("AHU-1/MYSTERY", "°C", [5.0] * 12))           # no role
    ef = build_frame("AHU-1", "ahu", rows, reg)
    assert ef.frame[R.SUPPLY_AIR_TEMP.value].iloc[0] == pytest.approx(15.0)
    assert ef.frame[R.DUCT_STATIC_PRESSURE.value].iloc[0] == pytest.approx(249.0889)
    assert ef.unconvertible == {"AHU-1/OAT": "furlongs"}
    assert set(ef.frame.columns) == {R.SUPPLY_AIR_TEMP.value, R.DUCT_STATIC_PRESSURE.value}


def test_frame_ignores_ambiguous_suggestions_unless_confirmed():
    reg = PointRoleRegistry()
    rows = _rows("VAV-3/SAT", "°C", [15.0] * 12)
    assert build_frame("VAV-3", "vav", rows, reg).frame.empty
    reg.set_explicit("VAV-3/SAT", "terminal-discharge-temp")
    ef = build_frame("VAV-3", "vav", rows, reg)
    assert ef.role_sources[R.TERMINAL_DISCHARGE_TEMP.value] == "explicit"


def _seed_ahu(db, eq="AHU-9", sat=21.0, hours=6):
    rng = np.random.default_rng(0)
    now = datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    pts = []
    for pid, unit, val, noise in ((f"{eq}/SF_STS", "", 1.0, 0.0), (f"{eq}/SAT", "°C", sat, 0.3),
                                  (f"{eq}/SAT_SP", "°C", 14.0, 0.0)):
        for i in range(hours * 12):
            pts.append({"point_id": pid, "equipment_id": eq,
                        "value": val + float(rng.normal(0, noise)) if noise else val, "unit": unit,
                        "timestamp": start + timedelta(minutes=5 * i)})
    return db.save_data_points_batch(pts)


def test_detect_equipment_faults_tool_returns_rule_findings(tmp_path, monkeypatch):
    """The LLM tool used to always answer 'model not loaded'; it now runs the rules."""
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import BMSDatabase
    import agent_commercial.database as dbmod
    from agent_commercial.tools.handlers.ml import MLHandlerMixin

    db = BMSDatabase(db_path=str(tmp_path / "tool.db"))
    monkeypatch.setattr(dbmod, "get_database", lambda *a, **k: db)

    class H(MLHandlerMixin):
        bms_state = BMSStateEngine()

    async def go():
        await _seed_ahu(db)
        out = await H()._handle_detect_equipment_faults({"equipment_id": "AHU-9"})
        none = await H()._handle_detect_equipment_faults({"equipment_id": "NOPE-1"})
        await db.close()
        return out, none

    out, none = asyncio.run(go())
    assert out["status"] == "fault" and out["confidence"] is None
    assert [f["rule_id"] for f in out["faults"]] == ["AHU-SATDEV"]
    assert out["faults"][0]["points_used"]["supply-air-temp"] == "AHU-9/SAT"
    assert any(n["rule_id"] == "FC14" and n["outcome"] == "skip" for n in out["not_evaluated"])
    assert 0 < out["health_score"] < 100
    assert none["status"] == "unknown" and none["faults"] == [] and none["health_score"] is None


def test_sweep_announces_only_newly_confirmed_faults(tmp_path):
    from types import SimpleNamespace
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import BMSDatabase
    from agent_commercial.main import OpsCopilot

    events = []
    db = BMSDatabase(db_path=str(tmp_path / "sweep.db"))
    ns = SimpleNamespace(fdd_engine=FDDEngine(poll_seconds=POLL), state_engine=BMSStateEngine(),
                         database=db, _event_bus=SimpleNamespace(publish=events.append))

    async def go():
        await _seed_ahu(db)
        first = await OpsCopilot.run_fdd_sweep(ns, hours=12)
        second = await OpsCopilot.run_fdd_sweep(ns, hours=12)
        await db.close()
        return first, second

    first, second = asyncio.run(go())
    assert len(events) == 1 and events[0]["type"] == "fdd_faults_confirmed"
    assert [f["rule_id"] for f in events[0]["payload"]["faults"]] == ["AHU-SATDEV"]
    assert first["counts"]["fail"] == 1 and second["new_faults"] == []


def test_run_building_end_to_end_with_persistence(tmp_path):
    from agent_commercial.bms_data_model import Equipment, EquipmentType
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import BMSDatabase
    from agent_commercial.fdd.store import latest_findings, save_findings

    async def go():
        db = BMSDatabase(db_path=str(tmp_path / "fdd.db"))
        state = BMSStateEngine()
        await state.register_equipment(Equipment(equipment_id="AHU-9", name="AHU 9",
                                                 equipment_type=EquipmentType.AHU))
        now = datetime.now().replace(second=0, microsecond=0)
        start = now - timedelta(hours=6)
        n = 72
        pts = []
        rng = np.random.default_rng(0)
        # Real sensors wobble; a perfectly constant SAT would (correctly) be flagged
        # by SV-FLATLINE as stuck and make the SAT rules INVALID.
        for pid, unit, val, noise in (("AHU-9/SF_STS", "", 1.0, 0.0), ("AHU-9/SAT", "°C", 21.0, 0.3),
                                      ("AHU-9/SAT_SP", "°C", 14.0, 0.0)):
            for i in range(n):
                pts.append({"point_id": pid, "equipment_id": "AHU-9",
                            "value": val + float(rng.normal(0, noise)) if noise else val, "unit": unit,
                            "timestamp": start + timedelta(minutes=5 * i)})
        await db.save_data_points_batch(pts)
        eng = FDDEngine(poll_seconds=POLL)
        findings = await eng.run_building(state, db, hours=12)
        run_id = await save_findings(db, findings)
        latest = await latest_findings(db, equipment_id="AHU-9", outcome="fail")
        await db.close()
        return findings, run_id, latest

    findings, run_id, latest = asyncio.run(go())
    by_rule = {f.rule_id: f for f in findings if f.equipment_id == "AHU-9"}
    assert by_rule["AHU-SATDEV"].outcome is Outcome.FAIL
    assert by_rule["AHU-SATDEV"].points_used[R.SUPPLY_AIR_TEMP.value] == "AHU-9/SAT"
    assert by_rule["FC14"].outcome is Outcome.SKIP                    # no coil sensors mapped
    assert run_id and any(r["rule_id"] == "AHU-SATDEV" for r in latest)
