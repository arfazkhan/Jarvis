"""
Phase 5 — access control, people counters and bookings → occupancy.

Real: EventIngest on a real BMSDatabase, the emit path into a real BMSStateEngine,
the event correlator, the attention gate's signal normalisers, the occupancy
provider, the `events` source kind, the API token check. Scripted: nothing — the
events are what an access-control system would send.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import BMSDataPoint
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.event_ingest import EventIngest, events_authorized

CFG = {"doors": {"DOOR-L5-E": {"zone": "L5", "direction": "in"}, "DOOR-L5-X": {"zone": "L5", "direction": "out"},
                 "DOOR-L6": {"zone": "L6"}},
       "zones": {"L5": {"name": "Floor 5", "reset_at": "03:00",
                        "conditioned_by": [{"point": "AHU-05/SF_STS"}, {"point": "VAV-5-01/DMPR", "above": 20}]},
                 "L6": {"name": "Floor 6", "presence_window_min": 60}},
       "rooms": {"Meeting Room 5A": "L5"}, "empty_after_min": 45}
T0 = datetime(2026, 10, 25, 17, 0)


@pytest_asyncio.fixture
async def ing(tmp_path):
    from agent_commercial.database import BMSDatabase
    from agent_commercial.event_correlator import EventCorrelator
    db = BMSDatabase(db_path=str(tmp_path / "e.db"))
    se = BMSStateEngine()
    published = []
    clock = {"t": T0}
    e = EventIngest(db, emit=se.update_point, publish=lambda t, p: published.append((t, p)),
                    correlator=EventCorrelator(se), state_engine=se, clock=lambda: clock["t"])
    e.configure("access", CFG)
    e.se, e.published, e.clock_ref = se, published, clock
    yield e
    await db.close()


def _val(e, pid):
    p = e.se._points.get(pid)
    return None if p is None else p.value


@pytest.mark.asyncio
async def test_badges_in_and_out_count_people_in_a_zone(ing):
    for i, door in enumerate(["DOOR-L5-E", "DOOR-L5-E", "DOOR-L5-E", "DOOR-L5-X"]):
        await ing.ingest("access", {"type": "badge", "door": door, "at": T0 + timedelta(minutes=i), "id": f"e{i}"})
    assert (_val(ing, "L5/OCC_COUNT"), _val(ing, "L5/OCCUPIED")) == (2.0, 1.0)
    assert ing.se._points["L5/OCCUPIED"].source == "event:access"
    kinds = [ev.event_type for ev in ing.correlator.event_history]
    assert kinds == ["badge_in", "badge_in", "badge_in", "badge_out"]       # the correlator hears every one


@pytest.mark.asyncio
async def test_entries_only_doors_give_presence_not_a_count(ing):
    await ing.ingest("access", {"type": "badge", "door": "DOOR-L6", "at": T0})
    assert "L6/OCC_COUNT" not in ing.se._points and _val(ing, "L6/OCCUPIED") == 1.0
    await ing.tick(T0 + timedelta(minutes=61))                            # past the 60-min window
    assert _val(ing, "L6/OCCUPIED") == 0.0


@pytest.mark.asyncio
async def test_identity_never_reaches_the_database(ing):
    await ing.ingest("access", {"type": "badge", "door": "DOOR-L5-E", "at": T0, "card": "0x9F3C21",
                                "name": "Ahmed Al-Thani", "employee_id": "E1029"})
    conn = await ing.database._get_async_connection()
    async with conn.execute("SELECT * FROM occupancy_events") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]
    flat = " ".join(str(x) for r in rows for x in r)
    assert "0x9F3C21" not in flat and "Ahmed" not in flat and "E1029" not in flat
    async with conn.execute("PRAGMA table_info(occupancy_events)") as cur:
        cols = {r[1] for r in await cur.fetchall()}
    assert not cols & {"card", "name", "employee_id", "person", "user"}


@pytest.mark.asyncio
async def test_retried_events_are_counted_once_and_bad_ones_are_named(ing):
    ev = {"type": "badge", "door": "DOOR-L5-E", "at": T0, "id": "acs-77"}
    assert await ing.ingest("access", ev) is not None
    assert await ing.ingest("access", ev) is None                          # the webhook retried
    assert _val(ing, "L5/OCC_COUNT") == 1.0
    with pytest.raises(ValueError, match="has no zone"):
        await ing.ingest("access", {"type": "badge", "door": "DOOR-UNKNOWN"})
    with pytest.raises(ValueError, match="event type"):
        await ing.ingest("access", {"type": "teleport", "zone": "L5"})


@pytest.mark.asyncio
async def test_floor_5_empty_but_still_cooled_is_flagged_once_and_cleared(ing):
    await ing.se.update_point(BMSDataPoint(point_id="AHU-05/SF_STS", name="fan", value=1, source="bacnet"))
    await ing.se.update_point(BMSDataPoint(point_id="VAV-5-01/DMPR", name="damper", value=65, unit="%", source="bacnet"))
    await ing.ingest("access", {"type": "badge", "door": "DOOR-L5-E", "at": T0})
    await ing.ingest("access", {"type": "badge", "door": "DOOR-L5-X", "at": T0 + timedelta(minutes=70)})   # 18:10
    for m in (80, 110, 120, 150):
        await ing.tick(T0 + timedelta(minutes=m))
    flagged = [p for t, p in ing.published if t == "zone_empty_but_conditioned"]
    assert len(flagged) == 1                                               # once per episode
    (p,) = flagged
    assert p["zone"] == "L5" and p["empty_since"].endswith("18:10") and p["minutes"] >= 45
    assert p["running"] == ["AHU-05/SF_STS at 1", "VAV-5-01/DMPR at 65 %"]
    await ing.se.update_point(BMSDataPoint(point_id="AHU-05/SF_STS", name="fan", value=0, source="bacnet"))
    await ing.se.update_point(BMSDataPoint(point_id="VAV-5-01/DMPR", name="damper", value=5, unit="%", source="bacnet"))
    await ing.tick(T0 + timedelta(minutes=160))
    assert ing.published[-1] == ("zone_empty_but_conditioned_cleared",
                                 {"zone": "L5", "name": "Floor 5", "why": "conditioning stopped"})

    from agent_commercial.ops_engineer.signals import to_signals
    (sig,) = to_signals({"type": "zone_empty_but_conditioned", "payload": p})
    assert sig.severity == "medium" and sig.topic == "empty:L5"
    assert "Floor 5 (L5) has had nobody in it since 18:10" in sig.facts and "AHU-05/SF_STS at 1" in sig.facts


@pytest.mark.asyncio
async def test_people_counters_bookings_and_the_nightly_reset(ing):
    await ing.ingest("access", {"type": "people_count", "zone": "L6", "count": 14, "at": T0})
    assert _val(ing, "L6/OCC_COUNT") == 14.0
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:bk-1\r\nDTSTART:20261025T180000\r\nDTEND:20261025T190000\r\n"
           "LOCATION:Meeting Room 5A\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:bk-2\r\nDTSTART:20261025T180000\r\n"
           "DTEND:20261025T190000\r\nLOCATION:Somewhere Else\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    assert await ing.import_ics("access", ics) == {"ingested": 1, "duplicates": 0, "skipped": 1}
    await ing.tick(datetime(2026, 10, 25, 18, 30))
    assert _val(ing, "L5/BOOKED") == 1.0
    await ing.tick(datetime(2026, 10, 25, 19, 30))
    assert _val(ing, "L5/BOOKED") == 0.0
    await ing.ingest("access", {"type": "badge", "door": "DOOR-L5-E", "at": datetime(2026, 10, 25, 20, 0)})
    await ing.tick(datetime(2026, 10, 26, 3, 0))                            # nobody badged out of the fire exit
    assert _val(ing, "L5/OCC_COUNT") == 0.0


@pytest.mark.asyncio
async def test_a_badge_export_csv_ignores_names_and_cards(ing):
    csv_text = ("Time,Door,Direction,Card Holder,Card Number\n"
                "2026-10-25 08:01:00,DOOR-L5-E,in,Sara K,0012\n"
                "2026-10-25 08:02:00,DOOR-L5-E,in,Ali R,0034\n"
                "2026-10-25 08:03:00,DOOR-NOPE,in,X,1\n")
    out = await ing.import_csv("access", csv_text)
    assert out["ingested"] == 2 and out["errors"][0]["line"] == 4
    assert _val(ing, "L5/OCC_COUNT") == 2.0
    assert (await ing.import_csv("access", csv_text))["duplicates"] == 2   # the same file again


def test_measured_occupancy_beats_co2_guesswork():
    from agent_commercial.gsas_occupancy_context import OccupancyContextProvider
    se = BMSStateEngine()
    asyncio.run(se.update_point(BMSDataPoint(point_id="L5/OCCUPIED", name="o", value=0, source="event:access")))
    asyncio.run(se.update_point(BMSDataPoint(point_id="L5/OCC_COUNT", name="c", value=0, source="event:access")))
    out = OccupancyContextProvider(bms_state_engine=se).get_zone_occupancy("L5")
    assert out["source"].startswith("measured") and out["current_occupancy_probability"] == 0.0 and out["people"] == 0


def test_the_events_webhook_token_fails_closed(monkeypatch):
    monkeypatch.delenv("ARVIS_EVENTS_TOKEN", raising=False)
    assert not events_authorized({"x-arvis-events-token": "anything"})
    monkeypatch.setenv("ARVIS_EVENTS_TOKEN", "t0k")
    assert events_authorized({"x-arvis-events-token": "t0k"}) and not events_authorized({"x-arvis-events-token": "no"})


def test_the_events_source_kind_configures_ingestion(tmp_path):
    from types import SimpleNamespace
    from agent_commercial.database import BMSDatabase
    from agent_commercial.main import OpsCopilot
    from agent_commercial.sources import SourceManager

    async def go():
        db = BMSDatabase(db_path=str(tmp_path / "k.db"))
        se = BMSStateEngine()
        ops = SimpleNamespace(state_engine=se, source_manager=SourceManager(), _bms_connected=False,
                              bacnet_adapter=None, modbus_adapter=None, opcua_adapter=None, mode="multi",
                              sources_config=[{"id": "access", "kind": "events", **CFG}])
        ops._wire_adapter = lambda a: None
        ops.event_ingest = EventIngest(db, emit=se.update_point, state_engine=se)
        await OpsCopilot._start_sources(ops)
        zones = sorted(ops.event_ingest.zones)
        stats = ops.source_manager.stats()
        await db.close()
        return zones, stats
    zones, stats = asyncio.run(go())
    assert zones == ["L5", "L6"] and stats[0]["watch"] is False
