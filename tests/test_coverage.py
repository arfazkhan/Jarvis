"""
Phase 3 — the equipment catalog, coverage, topology, and alarms for every source.

Real: config/equipment_catalog.yaml, coverage.assess on a real BMSStateEngine +
role registry, ManualReadingStore on a real BMSDatabase, RuleAlarms through the
state engine's own alarm path, commissioning + topology. Scripted: nothing but the
language model in the engineer-tool test.
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from agent_commercial.bms_data_model import AlarmState, BMSDataPoint, Equipment, EquipmentType, PointQuality
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.coverage import assess, load_catalog
from agent_commercial.semantics import get_role_registry
from agent_commercial.semantics.point_roles import PointRole, equipment_kind


def test_the_catalog_only_names_real_roles_and_known_kinds():
    cat = load_catalog()
    roles = {r.value for r in PointRole}
    for kind, spec in cat["kinds"].items():
        for need in spec["required"] + spec["optional"]:
            for r in (need if isinstance(need, tuple) else (need,)):
                assert r in roles, f"{kind}: {r} is not a PointRole"
        for r, way in (spec.get("how") or {}).items():
            assert r == "default" or r in roles, f"{kind}: how.{r}"
            assert way in cat["how_to"], f"{kind}: {way} has no advice"
    for t in EquipmentType:
        k = equipment_kind(t)
        assert k == "other" or k in cat["kinds"], f"{t} maps to {k}, which the catalog doesn't describe"


def _pt(pid, v, src, eq=None):
    return BMSDataPoint(point_id=pid, name=pid, value=v, source=src, equipment_id=eq or pid.split("/")[0])


async def _abuilding():
    """A partial-BMS building: an AHU on the BMS, a generator half on an I/O module, a tank read by hand."""
    se = BMSStateEngine()
    for eid, t in (("AHU-01", EquipmentType.AHU), ("GEN-1", EquipmentType.GENERATOR),
                   ("TANK-1", EquipmentType.WATER_TANK), ("WIDGET-9", EquipmentType.OTHER)):
        await se.register_equipment(Equipment(equipment_id=eid, name=eid, equipment_type=t))
    for p in (_pt("AHU-01/SAT", 13.0, "bacnet"), _pt("AHU-01/SF_STS", 1, "bacnet"), _pt("GEN-1/RUN", 0, "modbus:io"),
              _pt("GEN-1/FUEL", 70, "manual")):
        await se.update_point(p)
    return se


def _building():
    return asyncio.run(_abuilding())


def test_coverage_tells_connected_manual_and_missing_apart():
    from types import SimpleNamespace
    se = _building()
    tank = SimpleNamespace(point_id="TANK-1/LVL", equipment_id="TANK-1", role="tank-level")   # declared, not read yet
    rep = assess(se, [tank])
    eqs = {e["equipment_id"]: e for e in rep["equipment"]}
    assert eqs["AHU-01"]["score"] == {"connected": 2, "manual": 0, "imported": 0, "missing": 0}
    gen = {n["need"]: n["state"] for n in eqs["GEN-1"]["required"]}
    assert gen == {"run-status": "connected", "common-alarm": "missing", "fuel-level": "manual"}
    assert eqs["TANK-1"]["required"] == [{"need": "tank-level", "state": "manual"}]
    assert rep["unrecognised_equipment"] == ["WIDGET-9"]
    assert rep["totals"] == {"connected": 3, "manual": 2, "imported": 0, "missing": 1}
    assert rep["level"] == "Partial"                                         # 3 of 6 needs read by instruments
    first = rep["next"][0]
    assert (first["equipment_id"], first["role"], first["how"]) == ("GEN-1", "common-alarm", "bms")


def test_the_ladder_levels():
    async def go(points):
        se = BMSStateEngine()
        await se.register_equipment(Equipment(equipment_id="TANK-1", name="t", equipment_type=EquipmentType.WATER_TANK))
        await se.register_equipment(Equipment(equipment_id="SUMP-1", name="s", equipment_type=EquipmentType.SUMP_PUMP))
        for p in points:
            await se.update_point(p)
        return assess(se)["level"]
    assert asyncio.run(go([])) == "Unknown"
    assert asyncio.run(go([_pt("TANK-1/LVL", 50, "manual")])) == "Manual"
    assert asyncio.run(go([_pt("TANK-1/LVL", 50, "modbus"), _pt("SUMP-1/RUN", 1, "modbus"),
                           _pt("SUMP-1/HIGH", 0, "modbus")])) == "Full"


def test_next_steps_for_hvac_rank_by_the_fault_checks_they_switch_on():
    async def go():
        se = BMSStateEngine()
        await se.register_equipment(Equipment(equipment_id="AHU-02", name="a", equipment_type=EquipmentType.AHU))
        for p in (_pt("AHU-02/SAT", 13, "bacnet"), _pt("AHU-02/SF_STS", 1, "bacnet")):
            await se.update_point(p)
        return assess(se)["next"]
    nxt = asyncio.run(go())
    assert nxt and all(not n["required"] for n in nxt)                     # required is complete
    assert all(n["unlocks_fault_checks"] >= 1 for n in nxt)
    assert nxt == sorted(nxt, key=lambda n: -n["unlocks_fault_checks"])


# ── alarms for any source ────────────────────────────────────────────────────
def test_a_lift_fault_contact_raises_and_clears_an_alarm():
    from agent_commercial.alarms.rule_alarms import RuleAlarms

    async def go():
        se = BMSStateEngine()
        ra = RuleAlarms(se)
        ra.load([{"point_id": "LIFT-1/FAULT", "equipment_id": "LIFT-1",
                  "alarm_when": {"op": "==", "value": 1, "severity": "high", "message": "Lift 1 is in fault"}}])
        ra.attach()
        await se.update_point(_pt("LIFT-1/FAULT", 1, "modbus:io"))
        await asyncio.sleep(0)
        await asyncio.gather(*ra._tasks)
        raised = [a for a in se._alarms.values() if a.state != AlarmState.RESOLVED]
        await se.update_point(_pt("LIFT-1/FAULT", 0, "modbus:io"))
        await asyncio.sleep(0)
        await asyncio.gather(*ra._tasks)
        open_after = [a for a in se._alarms.values() if a.state != AlarmState.RESOLVED]
        return raised, open_after
    raised, open_after = asyncio.run(go())
    (a,) = raised
    assert (a.equipment_id, a.severity.value, a.message) == ("LIFT-1", "high", "Lift 1 is in fault (1)")
    assert open_after == []


def test_a_threshold_alarm_waits_for_its_delay_and_uses_hysteresis():
    from agent_commercial.alarms.rule_alarms import RuleAlarms, rule_from_config
    rule = rule_from_config({"point_id": "TX-1/TEMP", "alarm_when": {"op": ">", "value": 110, "for_s": 300,
                                                                    "clear_below": 100, "severity": "high"}})

    async def go():
        se = BMSStateEngine()
        ra = RuleAlarms(se)
        t0 = datetime(2026, 10, 25, 10, 0)
        steps = [(115, 0), (116, 120), (117, 301), (105, 400), (99, 500)]
        return [await ra.evaluate(rule, v, t0 + timedelta(seconds=s)) for v, s in steps]
    assert asyncio.run(go()) == [None, None, "raised", None, "cleared"]   # 105 is still above clear_below


def test_dead_sensors_never_alarm_and_bad_rules_are_named():
    from agent_commercial.alarms.rule_alarms import RuleAlarms, rule_from_config
    se = BMSStateEngine()
    ra = RuleAlarms(se)
    ra.load([{"point_id": "TANK-1/LVL", "alarm_when": {"op": "<", "value": 20}}])
    p = _pt("TANK-1/LVL", 5, "mqtt"); p.quality = PointQuality.BAD
    ra.on_point(p)
    assert not ra._tasks
    with pytest.raises(ValueError, match="op must be one of"):
        rule_from_config({"point_id": "X/Y", "alarm_when": {"op": "~", "value": 1}})
    with pytest.raises(ValueError, match="severity"):
        rule_from_config({"point_id": "X/Y", "alarm_when": {"op": ">", "value": 1, "severity": "huge"}})


def test_alarm_rules_load_from_every_source_in_the_site_config():
    from types import SimpleNamespace
    from agent_commercial.main import OpsCopilot
    ns = SimpleNamespace(state_engine=BMSStateEngine(), bacnet_config={}, opcua_config={}, modbus_config={
        "io_modules": [{"template": "digital_inputs", "channels": {
            0: {"point_id": "LIFT-1/FAULT", "alarm_when": {"op": "==", "value": 1, "severity": "high"}}}}]},
        sources_config=[{"id": "rounds", "kind": "manual", "points": [
            {"point_id": "GEN-1/FUEL", "unit": "%", "alarm_when": {"op": "<", "value": 25, "severity": "medium"}}]}])
    ns._config_point_entries = lambda: OpsCopilot._config_point_entries(ns)
    assert OpsCopilot._register_config_alarms(ns) == 2
    assert set(ns.rule_alarms.rules) == {"LIFT-1/FAULT", "GEN-1/FUEL"}


# ── topology from commissioning ──────────────────────────────────────────────
def test_serves_and_fed_by_become_the_topology(tmp_path):
    from agent_commercial.commissioning import commission_building
    from agent_commercial.topology import _downstream

    async def go():
        se = BMSStateEngine()
        spec = {"equipment": [
            {"id": "CHWP-1", "type": "pump", "serves": ["AHU-07"]},
            {"id": "AHU-07", "type": "air_handling_unit"},
            {"id": "VAV-7-01", "type": "variable_air_volume", "fed_by": "AHU-07"},
            {"id": "VAV-7-02", "type": "variable_air_volume", "fed_by": ["AHU-07", "NOPE-1"]},
        ]}
        counts = await commission_building(spec, se, None)
        by_id = dict(se._equipment)
        return counts, by_id
    counts, by_id = asyncio.run(go())
    assert counts["topology_links"] == 3
    assert by_id["AHU-07"].parent_equipment_id == "CHWP-1"
    assert by_id["VAV-7-01"].parent_equipment_id == "AHU-07"
    assert _downstream("CHWP-1", by_id) == ["AHU-07", "VAV-7-01", "VAV-7-02"]


# ── asked on WhatsApp ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_engineer_answers_what_cant_you_see(site):
    from tests.test_ops_engineer import ScriptedLLM, call, say, SARA
    llm = ScriptedLLM(call("coverage"), say("I see the AHUs well; the generator's alarm isn't connected yet."))
    eng, gw = site.build(llm)
    se = await _abuilding()
    eng.coverage = lambda: _async(assess(se))
    await gw.on_inbound(SARA, "what can't you see in the building?")
    out = json.loads(next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")["content"])
    assert (out["level"], out["instrumented"], out["covered"]) == ("Partial", "50%", "67%")
    assert out["next"][0]["role"] == "common-alarm"


async def _async(v):
    return v


from tests.test_ops_engineer import site  # noqa: E402,F401
