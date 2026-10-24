"""Phase 1 — canonical point roles, unit conversion and point-config import."""
import asyncio
import math
from types import SimpleNamespace

import pytest

from agent_commercial.bms_data_model import EquipmentType
from agent_commercial.semantics import (
    PointRole as R, PointRoleRegistry, equipment_kind, get_role_registry,
    parse_role, suggest_role, to_canonical,
)


def test_parse_role_accepts_both_spellings():
    assert parse_role("supply-air-temp") is R.SUPPLY_AIR_TEMP
    assert parse_role("SUPPLY_AIR_TEMP") is R.SUPPLY_AIR_TEMP
    assert parse_role(R.CHW_DP) is R.CHW_DP
    assert parse_role("not-a-role") is None


@pytest.mark.parametrize("etype,eid,kind", [
    (EquipmentType.AHU, "X", "ahu"), (None, "FAHU-1", "ahu"), (None, "SCHWP-02", "pump"),
    (None, "CH-3", "chiller"), (None, "CHW-PLANT", "plant"), (None, "VAV-3-12", "vav"),
    ("fan_coil_unit", "", "fcu"), (None, "LIFT-1", "lift"), (None, "WIDGET-1", "other"),
])
def test_equipment_kind(etype, eid, kind):
    assert equipment_kind(etype, eid) == kind


def test_suggestions_are_exact_or_kind_dependent():
    assert suggest_role("AHU-01/SAT", "ahu") == (R.SUPPLY_AIR_TEMP, 0.9)
    assert suggest_role("VAV-3/SAT", "vav") == (R.TERMINAL_DISCHARGE_TEMP, 0.7)
    assert suggest_role("CH-01/CHWST", "chiller") == (R.CHW_SUPPLY_TEMP, 0.9)
    assert suggest_role("METER/KWH", "meter") == (R.ELECTRIC_ENERGY, 0.9)
    assert suggest_role("METER/KW", "meter") == (R.ELECTRIC_POWER, 0.9)
    assert suggest_role("CHWP-1/DP", "pump") == (R.CHW_DP, 0.7)
    assert suggest_role("AHU-01/DP", "ahu") == (None, 0.0)        # ambiguous → unmapped
    assert suggest_role("XYZ/FOO", "other") == (None, 0.0)


@pytest.mark.parametrize("value,unit,role,expected", [
    (68, "°F", R.SUPPLY_AIR_TEMP, 20.0),
    (68, "degreesFahrenheit", R.SUPPLY_AIR_TEMP, 20.0),
    (20, "degC", R.SUPPLY_AIR_TEMP, 20.0),
    (293.15, "K", R.ZONE_TEMP, 20.0),
    (1.0, "inchesOfWater", R.DUCT_STATIC_PRESSURE, 249.0889),
    (1.5, "in.w.c.", R.DUCT_STATIC_PRESSURE, 373.63335),
    (45, "%", R.COOLING_VALVE, 0.45),
    (0.45, "", R.COOLING_VALVE, 0.45),
    (45, "", R.COOLING_VALVE, 0.45),                 # open-fdd command normalisation
    (1000, "cubicFeetPerMinute", R.SUPPLY_AIRFLOW, 0.471947),
    (100, "gpm", R.CHW_FLOW, 6.30902),
    (36, "m3/h", R.CHW_FLOW, 10.0),
    (100, "tonsRefrigeration", R.THERMAL_POWER, 351.685),
    (1500, "W", R.ELECTRIC_POWER, 1.5),
    (1, "active", R.SUPPLY_FAN_STATUS, None),        # unit must be a unit
    (1, "", R.SUPPLY_FAN_STATUS, 1.0),
])
def test_to_canonical(value, unit, role, expected):
    got = to_canonical(value, unit, role)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, rel=1e-5)


def test_to_canonical_never_guesses():
    assert to_canonical(21.0, "", R.SUPPLY_AIR_TEMP) is None       # temperature needs a unit
    assert to_canonical(5, "furlongs", R.CHW_FLOW) is None
    assert to_canonical(float("nan"), "°C", R.ZONE_TEMP) is None
    assert to_canonical("n/a", "°C", R.ZONE_TEMP) is None


def test_registry_explicit_beats_suggested_and_reports_conflicts():
    reg = PointRoleRegistry()
    reg.set_explicit("AHU-01/TEMP_1", "supply-air-temp")
    chosen, conflicts = reg.role_map(["AHU-01/SAT", "AHU-01/TEMP_1", "AHU-01/OAT"], "ahu")
    assert chosen[R.SUPPLY_AIR_TEMP].point_id == "AHU-01/TEMP_1"
    assert chosen[R.SUPPLY_AIR_TEMP].source == "explicit"
    assert chosen[R.OUTSIDE_AIR_TEMP].source == "suggested"
    _, conflicts = reg.role_map(["AHU-01/OAT", "AHU-01/OA_TEMP"], "ahu")
    assert conflicts == ["outside-air-temp: AHU-01/OAT vs AHU-01/OA_TEMP"]
    with pytest.raises(ValueError):
        reg.set_explicit("AHU-01/X", "banana")


def test_role_map_excludes_low_confidence_by_default():
    reg = PointRoleRegistry()
    chosen, _ = reg.role_map(["VAV-3/SAT"], "vav")
    assert chosen == {}
    chosen, _ = reg.role_map(["VAV-3/SAT"], "vav", min_confidence=0.7)
    assert R.TERMINAL_DISCHARGE_TEMP in chosen


def test_registry_attaches_to_state_engine_once():
    state = SimpleNamespace()
    assert get_role_registry(state) is get_role_registry(state)


# ── VOLTTRON registry import ──────────────────────────────────────────────────

_REG = """Point Name,Volttron Point Name,Units,Unit Details,BACnet Object Type,Property,Writable,Index,Notes,ARVIS Role
Supply Air Temp,SAT,degreesFahrenheit,,analogInput,presentValue,FALSE,3,,supply-air-temp
Cooling Valve,CLG_VLV,percent,,analogOutput,presentValue,TRUE,7,,
Broken,,percent,,analogValue,presentValue,FALSE,9,,
Bad role,OAT,degreesFahrenheit,,analogInput,presentValue,FALSE,4,,wibble
"""


def test_volttron_registry_import(tmp_path):
    from agent_commercial.semantics.volttron_registry import load_volttron_registry
    p = tmp_path / "ahu1.csv"
    p.write_text(_REG, encoding="utf-8")
    pts = load_volttron_registry(p, device_id=4001, equipment_id="AHU-01")
    assert [x["point_id"] for x in pts] == ["AHU-01/SAT", "AHU-01/CLG_VLV", "AHU-01/OAT"]
    sat = pts[0]
    assert sat["object_type"] == "analogInput" and sat["object_instance"] == 3
    assert sat["unit"] == "degreesFahrenheit" and sat["role"] == "supply-air-temp"
    assert pts[1]["writable_in_bms"] is True and "role" not in pts[1]
    assert "role" not in pts[2]                                    # unknown role ignored


def test_volttron_registry_rejects_other_csv(tmp_path):
    from agent_commercial.semantics.volttron_registry import load_volttron_registry
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_volttron_registry(p, 1, "AHU-01")


def test_site_config_expands_registries_and_registers_roles(tmp_path):
    from agent_commercial.main import OpsCopilot, build_protocol_configs
    (tmp_path / "ahu1.csv").write_text(_REG, encoding="utf-8")
    b, _ = build_protocol_configs({"bacnet": {
        "points": [{"point_id": "CH-01/T1", "device_id": 1, "object_type": "analogInput",
                    "object_instance": 1, "unit": "°C", "role": "chw-supply-temp"}],
        "registries": [{"csv": "ahu1.csv", "device_id": 4001, "equipment_id": "AHU-01"}],
    }}, base_dir=str(tmp_path))
    assert len(b["points_config"]["points"]) == 4

    state = SimpleNamespace()
    ns = SimpleNamespace(state_engine=state, bacnet_config=b, modbus_config={})
    ns._config_point_entries = lambda: OpsCopilot._config_point_entries(ns)
    assert OpsCopilot._register_config_roles(ns) == 2
    reg = get_role_registry(state)
    assert reg.resolve("CH-01/T1").role is R.CHW_SUPPLY_TEMP
    assert reg.resolve("AHU-01/SAT", "ahu").source == "explicit"


# ── Commissioning + discovery ─────────────────────────────────────────────────

def test_commissioning_registers_explicit_roles():
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.commissioning import commission_building
    state = BMSStateEngine()
    spec = {"equipment": [{"id": "AHU-07", "type": "air_handling_unit", "points": [
        {"point_id": "AHU-07/T_SUP", "unit": "C", "role": "supply-air-temp"},
        {"point_id": "AHU-07/Q", "role": "not-a-role"},
    ]}]}
    out = asyncio.run(commission_building(spec, state))
    assert out["roles_explicit"] == 1 and out["roles_invalid"] == 1
    assert get_role_registry(state).resolve("AHU-07/T_SUP").role is R.SUPPLY_AIR_TEMP


def test_discovery_draft_keeps_only_confident_or_confirmed_roles():
    from agent_commercial.discovery_commission import _draft_point, _promote_point
    sat = _draft_point(SimpleNamespace(point_id="AHU-01/SAT", name="", unit="C",
                                       point_type="sensor"), "ahu")
    vav = _draft_point(SimpleNamespace(point_id="VAV-3/SAT", name="", unit="C",
                                       point_type="sensor"), "vav")
    assert sat["role_needs_confirmation"] is False and vav["role_needs_confirmation"] is True
    assert _promote_point(sat)["role"] == "supply-air-temp"
    assert "role" not in _promote_point(vav)
    vav["role_confirmed"] = True
    assert _promote_point(vav)["role"] == "terminal-discharge-temp"
    assert "role_confidence" not in _promote_point(vav)


def test_recorder_ignores_commissioned_snapshot_values():
    from agent_commercial.bms_data_model import BMSDataPoint
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    rec = TelemetryRecorder(None)
    rec.on_point(BMSDataPoint(point_id="AHU-07/SAT", name="", value=16.5, source="commission"))
    assert rec.get_stats()["buffered"] == 0
