"""
Phase 2 — readings taken by people: the rung that works in every building.

Real: ManualReadingStore on a real BMSDatabase, the emit path into a real
BMSStateEngine, the gateway's deterministic reading paths, the proactive reading
rounds, the `manual` source kind through SourceManager, monitoring. Scripted: the
WhatsApp phone, the vision model (at its describe() interface), the language model.
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import BMSDataPoint, PointQuality
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.manual_readings import ManualReadingStore, Parsed, convert, parse_numbers, parse_numeric
from tests.test_ops_engineer import ALI, SARA, Phone, ScriptedLLM, call, say, site  # noqa: F401

TANK = {"point_id": "TANK-1/LVL", "name": "Tank 1 level", "equipment_id": "TANK-1", "unit": "%", "min": 0, "max": 100,
        "expected_interval_h": 12, "aliases": ["roof tank"]}
PUMP = {"point_id": "CHWP-1/DP", "name": "CHW pump 1 discharge", "equipment_id": "CHWP-1", "unit": "bar",
        "min": 0, "max": 10, "capture": "photo", "aliases": ["chwp 1"]}


@pytest_asyncio.fixture
async def store(tmp_path):
    from agent_commercial.database import BMSDatabase
    db = BMSDatabase(db_path=str(tmp_path / "r.db"))
    se = BMSStateEngine()
    s = ManualReadingStore(db, emit=se.update_point, state_engine=se)
    s.se = se
    for spec in (TANK, PUMP):
        await s.define_point(spec)
    yield s
    await db.close()


# ── what people type ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expect", [
    ("tank 1 62%", (62.0, "%", "tank 1")),
    ("CHWP-1 discharge 4,2 bar", (4.2, "bar", "CHWP-1 discharge")),
    ("1,250 kWh", (1250.0, "kWh", "")),
    ("٤٫٢ bar", (4.2, "bar", "")),                                   # Arabic-Indic digits
    ("AHU-07 SAT 13.5 °C", (13.5, "°C", "AHU-07 SAT")),
])
def test_numbers_are_read_with_their_unit_and_label(text, expect):
    (p,) = parse_numbers(text)
    assert (p.value, p.unit, p.label) == expect


def test_two_values_in_one_breath_are_never_guessed():
    assert parse_numeric("62 and 63") is None
    assert parse_numeric("4.1 or 4.2 bar") is None
    assert parse_numeric("not sure, can't read it") == "unsure"
    assert [(p.value, p.label) for p in parse_numbers("tank 1 62, chwp 1 4.2 bar")] == [(62.0, "tank 1"), (4.2, "chwp 1")]


def test_units_convert_between_what_was_typed_and_what_the_point_is_in():
    assert convert(420, "kPa", "bar") == pytest.approx(4.2)
    assert convert(77, "°F", "°C") == pytest.approx(25.0)
    assert convert(62, "", "%") == 62
    assert convert(4.2, "bar", "°C") is None


# ── the store ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_typed_reading_becomes_a_data_point(store):
    r = await store.record("TANK-1/LVL", 62, unit="%", technician=ALI)
    assert r.status == "confirmed" and r.confidence == .9
    p = store.se._points["TANK-1/LVL"]
    assert (p.value, p.source, p.quality, p.confidence, p.equipment_id) == (62.0, "manual", PointQuality.GOOD, .9, "TANK-1")


@pytest.mark.asyncio
async def test_doubtful_readings_wait_for_a_person(store):
    out = await store.record("TANK-1/LVL", 162, technician=ALI)                     # outside 0-100
    assert out.status == "pending_confirm" and "outside" in out.note and "TANK-1/LVL" not in store.se._points
    await store.record("TANK-1/LVL", 60, technician=ALI)
    jump = await store.record("TANK-1/LVL", 5, technician=ALI)                      # 60 → 5: more than half the range
    assert jump.status == "pending_confirm" and "big change" in jump.note
    assert store.se._points["TANK-1/LVL"].value == 60.0                              # not used until confirmed
    await store.confirm(jump.id, value=6, by="Ali")                                  # the right number
    assert store.se._points["TANK-1/LVL"].value == 6.0


@pytest.mark.asyncio
async def test_a_reading_of_a_live_point_is_a_free_sensor_check(store):
    await store.se.update_point(BMSDataPoint(point_id="CHWP-1/DP", name="dp", value=4.0, unit="bar", source="bacnet"))
    r = await store.record("CHWP-1/DP", 4.6, unit="bar", technician=ALI)
    assert r.status == "verification" and r.live_value == 4.0 and "+0.6" in r.note
    assert store.se._points["CHWP-1/DP"].value == 4.0                                # the instrument is not overwritten


@pytest.mark.asyncio
async def test_unknown_points_and_wrong_units_are_refused(store):
    with pytest.raises(ValueError, match="not a manual point"):
        await store.record("NOPE/X", 1)
    with pytest.raises(ValueError, match="in bar"):
        await store.record("CHWP-1/DP", 4.2, unit="°C")


@pytest.mark.asyncio
async def test_a_retried_api_call_is_counted_once(store):
    a = await store.record("TANK-1/LVL", 61, method="api", idempotency_key="k1")
    b = await store.record("TANK-1/LVL", 61, method="api", idempotency_key="k1")
    assert a.id == b.id and len(await store.history("TANK-1/LVL")) == 1


@pytest.mark.asyncio
async def test_overdue_readings_are_known(store):
    await store.record("TANK-1/LVL", 62, observed_at=datetime.now() - timedelta(hours=13))
    assert {p.point_id for p, _ in await store.overdue()} == {"TANK-1/LVL", "CHWP-1/DP"}
    await store.record("TANK-1/LVL", 63)
    assert {p.point_id for p, _ in await store.overdue()} == {"CHWP-1/DP"}


# ── over WhatsApp ────────────────────────────────────────────────────────────
def _wire(site, store, llm=None):
    eng, gw = site.build(llm or ScriptedLLM())
    gw.readings = eng.readings = store
    store.emit = site.state.update_point
    store.state_engine = site.state
    return eng, gw


@pytest.mark.asyncio
async def test_a_reading_round_goes_out_once_and_replies_fill_it_in(site):
    from types import SimpleNamespace
    from agent_commercial.ops_engineer.calendar import BuildingCalendar
    from agent_commercial.ops_engineer.proactive import ProactiveEngineer
    store = ManualReadingStore(site.db)
    for spec in (TANK, PUMP):
        await store.define_point(spec)
    await store.define_round({"name": "Morning plant round", "at": ["07:30"], "to": "+974 5550 1234",
                              "points": ["TANK-1/LVL", "CHWP-1/DP"]})
    eng, gw = _wire(site, store)
    pro = ProactiveEngineer(people=site.people, store=site.store, gateway=gw, engineer=eng,
                            gate=SimpleNamespace(), calendar=BuildingCalendar())
    pro.readings = store
    seven31 = datetime.now().replace(hour=7, minute=31).astimezone()
    assert await pro.send_rounds(seven31) == 1
    assert await pro.send_rounds(seven31 + timedelta(minutes=5)) == 0          # once per slot
    (msg,) = site.phone.to(ALI)
    assert msg.startswith("Morning plant round — time for these readings:") and "1. Tank 1 level (%)" in msg

    reply = await gw.on_inbound(ALI, "tank 1 62")
    assert reply.startswith("Got it: Tank 1 level 62 %.") and reply.endswith("Still need: CHW pump 1 discharge.")
    reply = await gw.on_inbound(ALI, "chwp 1 4.2 bar")
    assert reply == "Got it: CHW pump 1 discharge 4.2 bar.\nThat's the round done — thanks."
    assert site.state._points["CHWP-1/DP"].value == 4.2


@pytest.mark.asyncio
async def test_a_doubtful_reading_is_settled_with_yes_no_or_the_number(site):
    store = ManualReadingStore(site.db)
    await store.define_point(TANK)
    eng, gw = _wire(site, store)
    await store.record("TANK-1/LVL", 60, technician=ALI)
    await store.record("TANK-1/LVL", 5, technician=ALI)                              # big jump: waiting
    assert await gw.on_inbound(ALI, "sorry 55") == "Saved: Tank 1 level 55 %."
    assert site.state._points["TANK-1/LVL"].value == 55.0
    await store.record("TANK-1/LVL", 150, technician=ALI)
    assert (await gw.on_inbound(ALI, "no")).startswith("OK, I won't use that reading of Tank 1 level.")
    assert site.state._points["TANK-1/LVL"].value == 55.0


class Gauge:
    """The vision model at its describe() interface: reads a gauge as JSON."""
    available = True

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def describe(self, image, prompt, max_tokens=1024):
        self.prompts.append(prompt)
        return self.answer


@pytest.mark.asyncio
async def test_a_gauge_photo_becomes_a_reading_once_the_person_confirms_it(site, tmp_path):
    from tests.test_ops_media_group import MediaPhone, media_site, photo
    from agent_commercial.ops_engineer.media import PhotoReader
    store = ManualReadingStore(site.db)
    await store.define_point(PUMP)
    eng, gw = media_site(site, ScriptedLLM(), tmp_path, phone=MediaPhone({"G1": (b"\xff\xd8jpeg", "image/jpeg")}))
    gw.readings = store
    store.emit, store.state_engine = site.state.update_point, site.state
    gauge = Gauge('{"point_id": "CHWP-1/DP", "value": 4.2, "unit": "bar"}')
    gw.photos = PhotoReader(gauge)

    q = await gw.on_message(photo(ALI, "G1", caption="CHWP-1 discharge"))
    assert q == "From the photo I read 4.2 bar for CHW pump 1 discharge — is that right? Reply yes, no, or the correct number."
    assert "CHWP-1/DP: CHW pump 1 discharge (bar)" in gauge.prompts[0]
    assert "CHWP-1/DP" not in site.state._points                                      # not used yet
    assert await gw.on_inbound(ALI, "yes") == "Saved: CHW pump 1 discharge 4.2 bar."
    p = site.state._points["CHWP-1/DP"]
    assert (p.value, p.source, p.confidence) == (4.2, "manual", .85)                  # read by the model, checked by Ali
    (r,) = await store.history("CHWP-1/DP")
    assert r.method == "photo_ocr" and r.media_ref.startswith("ops_media:")


@pytest.mark.asyncio
async def test_an_illegible_gauge_falls_back_to_describing_the_photo(site, tmp_path):
    from tests.test_ops_media_group import MediaPhone, media_site, photo
    from agent_commercial.ops_engineer.media import PhotoReader
    store = ManualReadingStore(site.db)
    await store.define_point(PUMP)
    llm = ScriptedLLM(say("I can't make out the dial — could you send a closer photo?"))
    eng, gw = media_site(site, llm, tmp_path, phone=MediaPhone({"G2": (b"\xff\xd8jpeg", "image/jpeg")}))
    gw.readings = store
    gw.photos = PhotoReader(Gauge('{"value": null}'))
    reply = await gw.on_message(photo(ALI, "G2", caption="CHWP-1 discharge"))
    assert reply.startswith("I can't make out the dial") and await store.history("CHWP-1/DP") == []


@pytest.mark.asyncio
async def test_the_engineer_records_a_reading_said_in_conversation(site):
    store = ManualReadingStore(site.db)
    await store.define_point(TANK)
    llm = ScriptedLLM(call("record_reading", point="roof tank", value=58, unit="%"), say("Noted — roof tank at 58%."))
    eng, gw = _wire(site, store, llm)
    await gw.on_inbound(ALI, "fyi the roof tank is at 58% this morning")
    out = json.loads(next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")["content"])
    assert out == {"point": "Tank 1 level", "point_id": "TANK-1/LVL", "value": 58.0, "unit": "%", "status": "confirmed"}
    assert site.state._points["TANK-1/LVL"].value == 58.0


# ── the `manual` source kind ─────────────────────────────────────────────────
def test_manual_points_come_from_the_site_config_and_are_not_watched(tmp_path):
    from types import SimpleNamespace
    from agent_commercial.database import BMSDatabase
    from agent_commercial.main import OpsCopilot
    from agent_commercial.monitoring_health import MonitoringHealthWatcher, assess_monitoring
    from agent_commercial.sources import SourceManager

    async def go():
        db = BMSDatabase(db_path=str(tmp_path / "m.db"))
        se = BMSStateEngine()
        ops = SimpleNamespace(state_engine=se, data_source="UNAVAILABLE", _bms_connected=False, mode="multi",
                              source_manager=SourceManager(), bacnet_adapter=None, modbus_adapter=None, opcua_adapter=None)
        ops._wire_adapter = lambda a: None
        ops.manual_readings = ManualReadingStore(db, emit=se.update_point, state_engine=se)
        ops.sources_config = [{"id": "rounds", "kind": "manual", "points": [TANK, PUMP],
                               "rounds": [{"name": "Morning", "at": "07:30", "to": "group", "points": ["TANK-1/LVL"]}]}]
        await OpsCopilot._start_sources(ops)
        names = [p.point_id for p in await ops.manual_readings.points()]
        await ops.manual_readings.record("TANK-1/LVL", 40, observed_at=datetime.now() - timedelta(hours=5))
        a = assess_monitoring(ops, 15)
        state = MonitoringHealthWatcher(ops, publish=lambda *x: None)._classify(a)
        await db.close()
        return names, a, state
    names, a, state = asyncio.run(go())
    assert names == ["CHWP-1/DP", "TANK-1/LVL"]
    assert a["adapters"] == [] and a["total_points"] == 0                              # people don't go "offline"
    assert state == "unknown"                                                          # a manual-only site is not "blind"


def test_a_round_asking_for_undeclared_points_is_rejected():
    from agent_commercial.manual_readings import ManualSource
    with pytest.raises(ValueError, match="not declared"):
        ManualSource({}).load_points_from_config({"points": [TANK], "rounds": [{"name": "x", "points": ["NOPE/X"]}]})
