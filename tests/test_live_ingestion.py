"""
Regression tests for the live-ingestion foundation (Phase 0).

Each test pins a defect that made a real building learn nothing:
  * live kW hit a swallowed NameError and never reached the energy analyzer
  * `"KW" in point_id` fed cumulative METER/KWH in as kW
  * live telemetry was never persisted, so the calibrator/digests starved
  * the watchdog dropped CH-05..CH-08 and classed chilled-water pumps as chillers
  * BACnet non-numeric values became a fake GOOD 0.0; statusFlags were ignored
  * data_source read LIVE on socket bind, with zero points configured
  * Modbus readings were processed twice (double callback registration)
"""
import asyncio
import math
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_commercial.bms_data_model import BMSDataPoint, PointQuality


def _pt(pid, value, unit="", quality=PointQuality.GOOD, eq=None, ts=None):
    return BMSDataPoint(point_id=pid, name=pid, value=value, unit=unit,
                        equipment_id=eq or pid.split("/")[0], quality=quality,
                        timestamp=ts or datetime.now(timezone.utc), source="bacnet")


# ── Meter routing ─────────────────────────────────────────────────────────────

def test_power_meter_detection_excludes_kwh():
    from agent_commercial.main import _is_power_meter_point
    assert _is_power_meter_point(_pt("METER/KW", 600, "kW"))
    assert not _is_power_meter_point(_pt("METER/KWH", 1e6, "kWh"))
    # No unit configured → decided by the exact suffix, not a substring.
    assert _is_power_meter_point(_pt("CH-01/KW", 240))
    assert not _is_power_meter_point(_pt("METER/KWH", 1e6))
    assert not _is_power_meter_point(_pt("AHU-01/SAT", 14, "°C"))


def test_live_meter_ingest_reaches_energy_analyzer():
    """The live path used an EnergyReading name that only existed inside the
    simulator loop — every live kW reading raised NameError."""
    from agent_commercial.main import OpsCopilot
    got, water = [], []
    ns = SimpleNamespace(
        energy_analyzer=SimpleNamespace(add_reading=got.append),
        water_adapter=SimpleNamespace(ingest_reading=lambda **kw: water.append(kw)),
        _loop=None, database=None,
    )
    OpsCopilot._ingest_meter_point(ns, _pt("METER/KW", 612.5, "kW", eq="MAIN-METER"))
    OpsCopilot._ingest_meter_point(ns, _pt("METER/KWH", 1_234_567, "kWh", eq="MAIN-METER"))
    OpsCopilot._ingest_meter_point(ns, _pt("WTR-01/TOTAL_M3", 1250.0, "m³"))
    assert len(got) == 1 and got[0].value == 612.5 and got[0].unit == "kW"
    assert len(water) == 1 and water[0]["value_m3"] == 1250.0


# ── Telemetry persistence ─────────────────────────────────────────────────────

class _FakeDB:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    async def save_data_points_batch(self, rows):
        if self.fail:
            raise RuntimeError("disk full")
        self.rows.extend(rows)


def test_recorder_keeps_only_honest_numeric_values():
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    rec = TelemetryRecorder(_FakeDB())
    rec.on_point(_pt("AHU-01/SAT", 14.2, "°C"))
    rec.on_point(_pt("AHU-01/SAT", float("nan")))
    rec.on_point(_pt("AHU-01/SAT", None))
    rec.on_point(_pt("AHU-01/SAT", "active"))
    assert rec.get_stats()["buffered"] == 1
    assert rec.get_stats()["skipped_non_numeric"] == 3


def test_recorder_copies_fields_and_stores_naive_local_time():
    """The state engine passes its canonical, mutable point; the recorder must
    copy it. Aware UTC stamps are stored as naive local (what readers compare)."""
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    db = _FakeDB()
    rec = TelemetryRecorder(db)
    utc = datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc)
    p = _pt("CH-01/CHWST", 6.8, "°C", ts=utc)
    rec.on_point(p)
    p.value = 99.0  # later mutation must not leak into the stored row
    asyncio.run(rec.flush())
    row = db.rows[0]
    assert row["value"] == 6.8
    assert row["timestamp"].tzinfo is None
    assert row["timestamp"] == utc.astimezone().replace(tzinfo=None)


def test_recorder_keeps_rows_when_flush_fails():
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    rec = TelemetryRecorder(_FakeDB(fail=True))
    rec.on_point(_pt("AHU-01/SAT", 14.0))
    assert asyncio.run(rec.flush()) == 0
    assert rec.get_stats()["buffered"] == 1   # retried next cycle, not lost


def test_recorder_sees_only_state_engine_accepted_values():
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    db = _FakeDB()
    rec = TelemetryRecorder(db)
    state = BMSStateEngine()
    state.on_point_update(rec.on_point)
    state.update_point_sync(_pt("AHU-01/SAT", 14.0))
    state.suppress_point("AHU-01/SAT")
    state.update_point_sync(_pt("AHU-01/SAT", 999.0))   # suppressed → not stored
    asyncio.run(rec.flush())
    assert [r["value"] for r in db.rows] == [14.0]


def test_recorded_history_is_readable_from_real_db(tmp_path):
    """End-to-end: recorder → SQLite data_points → get_point_history."""
    from agent_commercial.database import BMSDatabase
    from agent_commercial.telemetry_recorder import TelemetryRecorder

    async def run():
        db = BMSDatabase(db_path=str(tmp_path / "t.db"))
        rec = TelemetryRecorder(db)
        now = datetime.now(timezone.utc)
        for i in range(5):
            rec.on_point(_pt("AHU-01/SAT", 14.0 + i, "°C", ts=now - timedelta(minutes=5 - i)))
        await rec.flush()
        hist = await db.get_point_history("AHU-01/SAT", hours=1)
        await db.close()
        return hist

    hist = asyncio.run(run())
    assert sorted(h["value"] for h in hist) == [14.0, 15.0, 16.0, 17.0, 18.0]


# ── Watchdog ──────────────────────────────────────────────────────────────────

def test_watchdog_does_not_drop_chillers_5_to_8():
    from agent_commercial.anomaly_watchdog import AnomalyWatchdog
    wd = AnomalyWatchdog(event_bus=None)
    wd.on_point_update(_pt("CH-06/CHWST", 7.0, "°C"))
    assert wd._stats["total_processed"] == 1


def test_watchdog_classifies_chw_pumps_as_pumps():
    from agent_commercial.anomaly_watchdog import AnomalyWatchdog
    wd = AnomalyWatchdog(event_bus=None)
    wd.calibrated_thresholds = {"type:pump:generic": (4.2, 1.0),
                                "type:chiller:generic": (9.9, 1.0)}
    wd._classify_point = lambda p: "generic"
    z, _floor = wd._get_threshold_and_floor(_pt("SCHWP-01/SPD", 80, eq="SCHWP-01"))
    assert z == 4.2


# ── BACnet value honesty ──────────────────────────────────────────────────────

def test_bacnet_coerce_numeric_never_invents_values():
    from agent_commercial.bacnet_adapter import coerce_numeric
    assert coerce_numeric(21.5) == 21.5
    assert coerce_numeric("active") == 1.0
    assert coerce_numeric("inactive") == 0.0
    assert coerce_numeric(True) == 1.0
    assert coerce_numeric("garbage") is None
    assert coerce_numeric(float("inf")) is None
    assert coerce_numeric(None) is None


def test_bacnet_status_flags_map_to_quality():
    from agent_commercial.bacnet_adapter import quality_from_status_flags as q
    assert q([0, 0, 0, 0]) == PointQuality.GOOD
    assert q([0, 1, 0, 0]) == PointQuality.BAD          # fault
    assert q([0, 0, 0, 1]) == PointQuality.BAD          # outOfService
    assert q([0, 0, 1, 0]) == PointQuality.OVERRIDDEN
    assert q(None) == PointQuality.UNCERTAIN


def test_bacnet_read_point_skips_non_numeric_and_marks_faults():
    from agent_commercial.bacnet_adapter import BACnetAdapter, BACnetDevice, BACnetPoint
    ad = BACnetAdapter()
    ad._devices[1] = BACnetDevice(device_id=1, device_name="d", address="10.0.0.5")
    reads = {}

    async def fake_read(device_address, object_type, object_instance,
                        property_name="presentValue", timeout=5.0):
        return reads[property_name]

    ad.read_property = fake_read
    cfg = BACnetPoint(device_id=1, object_type="analogInput", object_instance=1,
                      point_id="AHU-01/SAT", equipment_id="AHU-01", unit="°C")

    reads.update(presentValue="garbage", statusFlags=[0, 0, 0, 0])
    assert asyncio.run(ad.read_point(cfg)) is None                # not a fake 0.0

    reads.update(presentValue=13.9, statusFlags=[0, 1, 0, 0])
    p = asyncio.run(ad.read_point(cfg))
    assert p.value == 13.9 and p.quality == PointQuality.BAD


# ── Live status + wiring ──────────────────────────────────────────────────────

def _copilot_ns(**kw):
    from agent_commercial.bms_state_engine import BMSStateEngine
    ns = SimpleNamespace(state_engine=BMSStateEngine(), data_source="UNAVAILABLE",
                         _bms_connected=True, predictive_engine=None,
                         energy_analyzer=None, water_adapter=None)
    ns.__dict__.update(kw)
    ns._ingest_meter_point = lambda p: None
    return ns


def test_data_source_goes_live_on_first_real_reading_not_on_bind():
    from agent_commercial.main import OpsCopilot
    ns = _copilot_ns()
    OpsCopilot._on_point_update(ns, _pt("AHU-01/SAT", 14.0, quality=PointQuality.BAD))
    assert ns.data_source == "UNAVAILABLE"
    OpsCopilot._on_point_update(ns, _pt("AHU-01/RAT", 24.0))
    assert ns.data_source == "LIVE"


def test_production_refuses_bacnet_with_zero_points(monkeypatch):
    from agent_commercial.main import OpsCopilot
    monkeypatch.setenv("ARVIS_ENV", "production")
    ns = SimpleNamespace(bacnet_config={}, data_source="UNAVAILABLE", _bms_connected=False)
    with pytest.raises(RuntimeError, match="No BACnet points"):
        asyncio.run(OpsCopilot._start_bacnet(ns))


def test_adapter_wired_exactly_once():
    from agent_commercial.main import OpsCopilot
    cbs = []
    adapter = SimpleNamespace(on_point_update=cbs.append)
    ns = SimpleNamespace(bacnet_adapter=None, modbus_adapter=adapter,
                         _on_point_update=lambda p: None)
    ns._wire_adapter = lambda a: OpsCopilot._wire_adapter(ns, a)
    ns._wire_adapter(adapter)            # as _start_modbus does, before polling
    OpsCopilot._setup_callbacks(ns)      # used to re-register → double processing
    assert len(cbs) == 1


def test_site_config_split_into_protocol_configs():
    from agent_commercial.main import build_protocol_configs
    b, m = build_protocol_configs({
        "bacnet": {"port": 47808, "device_id": 4001, "poll_interval": 30,
                   "points": [{"point_id": "AHU-01/SAT", "device_id": 1,
                               "object_type": "analogInput", "object_instance": 3}]},
        "modbus": {"host": "10.0.0.9", "registers": []},
    })
    assert b["device_id"] == 4001 and b["poll_interval"] == 30
    assert len(b["points_config"]["points"]) == 1
    assert m["host"] == "10.0.0.9"
