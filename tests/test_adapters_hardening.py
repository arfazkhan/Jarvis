"""Phase 5 — BACnet / Modbus adapter hardening (VOLTTRON practices), no hardware needed."""
import asyncio
import struct
import time
from types import SimpleNamespace

import pytest

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import PointQuality


def run(coro):
    return asyncio.run(coro)


# ── BACnet ────────────────────────────────────────────────────────────────────

class FakeBACnetApp:
    def __init__(self, rpm_rows=None, rpm_error=None, single=None, iams=None):
        self.rpm_rows, self.rpm_error = rpm_rows, rpm_error
        self.single = single or {}
        self.iams = iams or []
        self.rpm_calls, self.single_calls = [], []

    async def read_property_multiple(self, address, params):
        self.rpm_calls.append(params)
        if self.rpm_error:
            raise self.rpm_error
        return self.rpm_rows(params) if callable(self.rpm_rows) else self.rpm_rows

    async def read_property(self, address, objid, prop):
        self.single_calls.append((str(objid), prop))
        return self.single[(str(objid), prop)]

    async def who_is(self):
        return self.iams


def _adapter(app, n=1, **kw):
    from agent_commercial.bacnet_adapter import BACnetAdapter, BACnetDevice, BACnetPoint
    ad = BACnetAdapter(**kw)
    ad._app = app
    ad._devices[7] = BACnetDevice(device_id=7, device_name="d7", address="10.0.0.7")
    for i in range(1, n + 1):
        ad.add_point(BACnetPoint(device_id=7, object_type="analogInput", object_instance=i,
                                 point_id=f"AHU-1/P{i}", equipment_id="AHU-1", unit="°C"))
    return ad


def test_single_read_builds_a_valid_object_identifier():
    """ObjectIdentifier(type, instance) raised ValueError and every read failed silently."""
    app = FakeBACnetApp(rpm_error=RuntimeError("unrecognized-service"),
                        single={("analog-input,1", "presentValue"): 21.5,
                                ("analog-input,1", "statusFlags"): [0, 0, 0, 0]})
    pts = run(_adapter(app).read_all_points())
    assert [(p.point_id, p.value, p.quality) for p in pts] == [("AHU-1/P1", 21.5, PointQuality.GOOD)]
    assert app.single_calls[0] == ("analog-input,1", "presentValue")


def _rows(values, flags=None):
    from bacpypes3.basetypes import PropertyIdentifier

    def build(params):
        out = []
        for oid, props in params:
            inst = int(str(oid).split(",")[1])
            out.append((oid, PropertyIdentifier("presentValue"), None, values[inst]))
            if "statusFlags" in props:
                out.append((oid, PropertyIdentifier("statusFlags"), None, (flags or {}).get(inst, [0, 0, 0, 0])))
        return out
    return build


def test_read_property_multiple_batches_values_and_status():
    app = FakeBACnetApp(rpm_rows=_rows({1: 12.0, 2: 13.0, 3: 14.0, 4: 15.0, 5: 16.0},
                                       flags={2: [0, 1, 0, 0], 3: [0, 0, 1, 0]}))
    ad = _adapter(app, n=5, max_per_request=2)
    pts = {p.point_id: p for p in run(ad.read_all_points())}
    assert len(app.rpm_calls) == 3 and ad.stats["rpm_requests"] == 3
    assert pts["AHU-1/P1"].value == 12.0 and pts["AHU-1/P1"].quality is PointQuality.GOOD
    assert pts["AHU-1/P2"].quality is PointQuality.BAD            # fault flag
    assert pts["AHU-1/P3"].quality is PointQuality.OVERRIDDEN
    assert not app.single_calls


def test_rpm_rejection_falls_back_to_single_reads_once():
    single = {}
    for i in (1, 2):
        single[(f"analog-input,{i}", "presentValue")] = 20.0 + i
        single[(f"analog-input,{i}", "statusFlags")] = [0, 0, 0, 0]
    app = FakeBACnetApp(rpm_error=RuntimeError("unrecognized-service"), single=single)
    ad = _adapter(app, n=2)
    assert len(run(ad.read_all_points())) == 2
    assert len(run(ad.read_all_points())) == 2
    assert len(app.rpm_calls) == 1 and ad.get_stats()["rpm_unsupported_devices"] == [7]


def test_per_point_poll_interval_is_honoured():
    app = FakeBACnetApp(rpm_rows=_rows({1: 1.0, 2: 2.0}))
    ad = _adapter(app, n=2)
    ad._poll_interval = 60
    ad._points["AHU-1/P2"].poll_interval_seconds = 3600
    run(ad.read_all_points(only_due=True))
    ad._points["AHU-1/P1"].last_polled -= __import__("datetime").timedelta(seconds=61)
    second = run(ad.read_all_points(only_due=True))
    assert [p.point_id for p in second] == ["AHU-1/P1"]


def test_silent_point_goes_stale_once_and_recorder_ignores_it():
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    app = FakeBACnetApp(rpm_rows=_rows({1: 9.0}))
    ad = _adapter(app)
    run(ad.read_all_points())
    ad._devices.clear()                                   # device goes silent
    ad._freshness._last_ok["AHU-1/P1"] = time.monotonic() - 10_000
    stale = run(ad.read_all_points())
    assert [(p.value, p.quality) for p in stale] == [(9.0, PointQuality.STALE)]
    assert run(ad.read_all_points()) == []                # reported once
    rec = TelemetryRecorder(None)
    rec.on_point(stale[0])
    assert rec.get_stats()["buffered"] == 0


def test_missing_devices_are_rediscovered():
    iam = SimpleNamespace(iAmDeviceIdentifier=("device", 9), pduSource="10.0.0.9", vendorID=5)
    app = FakeBACnetApp(rpm_rows=_rows({1: 1.0}), iams=[iam])
    from agent_commercial.bacnet_adapter import BACnetPoint
    ad = _adapter(app, rediscover_interval_s=0.0)
    ad.add_point(BACnetPoint(device_id=9, object_type="analogInput", object_instance=1,
                             point_id="CH-1/CHWST", equipment_id="CH-1", unit="°C"))
    assert ad.missing_devices() == [9]
    assert run(ad.maybe_rediscover()) is True
    assert ad.missing_devices() == [] and ad.stats["rediscoveries"] == 1


def test_point_freshness_timeout():
    f = PointFreshness(stale_factor=3.0)
    f.register("A", now=0.0)
    assert f.newly_stale({"A": 60}, now=170.0) == []
    assert f.newly_stale({"A": 60}, now=181.0) == ["A"]
    assert f.newly_stale({"A": 60}, now=500.0) == []
    f.mark_ok("A", now=501.0)
    assert f.stale_points == []


# ── Modbus ────────────────────────────────────────────────────────────────────

def _words(fmt, v):
    return list(struct.unpack(">HH", struct.pack(fmt, v)))


@pytest.mark.parametrize("dt,wo,bo,regs,expected", [
    ("float32", "big", "big", _words(">f", 12.5), 12.5),
    ("float32", "little", "big", _words(">f", 12.5)[::-1], 12.5),                  # CDAB
    ("float32", "big", "little",
     [((w & 0xFF) << 8) | (w >> 8) for w in _words(">f", -3.25)], -3.25),          # BADC
    ("int32", "big", "big", _words(">i", -70000), -70000.0),
    ("uint32", "little", "big", _words(">I", 123456)[::-1], 123456.0),
    ("int16", "big", "big", [0xFFFE], -2.0),
    ("uint16", "big", "big", [0xFFFE], 65534.0),
    ("float32", "big", "big", _words(">f", float("nan")), None),
])
def test_modbus_register_decoding(dt, wo, bo, regs, expected):
    from agent_commercial.modbus_adapter import ModbusPoint
    p = ModbusPoint("holding", 0, "M/P", data_type=dt, word_order=wo, byte_order=bo)
    got = p.decode(regs)
    assert got == (pytest.approx(expected) if expected is not None else None)


def test_modbus_scaling_and_bad_config():
    from agent_commercial.modbus_adapter import ModbusAdapter, ModbusPoint
    assert ModbusPoint("holding", 0, "X", scale=0.1, offset=-5).decode([250]) == pytest.approx(20.0)
    ad = ModbusAdapter(host="127.0.0.1")
    n = ad.load_points_from_config({"registers": [
        {"register_type": "holding", "address": 1, "point_id": "OK", "data_type": "float32"},
        {"register_type": "holding", "address": 2, "point_id": "BAD", "data_type": "float64"},
    ]})
    assert n == 1 and "OK" in ad._points


class FakeModbusClient:
    """Mimics pymodbus ≥ 3.9 (device_id keyword)."""
    def __init__(self, regs):
        self.regs, self.calls, self.connected = regs, [], True

    async def read_holding_registers(self, address, *, count=1, device_id=1, no_response_expected=False):
        self.calls.append((address, count, device_id))
        return SimpleNamespace(isError=lambda: False, registers=self.regs[address:address + count])

    def close(self):
        self.connected = False


def test_modbus_uses_the_installed_unit_keyword_and_reads_32bit():
    from agent_commercial.modbus_adapter import ModbusAdapter
    ad = ModbusAdapter(host="10.0.0.20", unit_id=4)
    ad._client, ad._is_connected = FakeModbusClient(_words(">f", 415.5)), True
    ad.load_points_from_config({"registers": [
        {"register_type": "holding", "address": 0, "point_id": "MTR/KW", "data_type": "float32",
         "unit": "kW"}]})
    pts = run(ad.read_all_points())
    assert pts[0].value == pytest.approx(415.5) and pts[0].quality is PointQuality.GOOD
    assert ad._client.calls == [(0, 2, 4)] and ad._unit_kwarg() == "device_id"


def test_modbus_keyword_for_older_pymodbus():
    from agent_commercial.modbus_adapter import ModbusAdapter

    class Old:
        async def read_holding_registers(self, address, count=1, slave=1):
            pass
    ad = ModbusAdapter(host="x")
    ad._client = Old()
    assert ad._unit_kwarg() == "slave"


def test_modbus_reconnects_with_backoff():
    from agent_commercial.modbus_adapter import ModbusAdapter
    ad = ModbusAdapter(host="10.0.0.20")
    attempts = []

    async def fake_connect():
        attempts.append(1)
        ok = len(attempts) >= 2
        ad._is_connected = ok
        ad._client = FakeModbusClient([0]) if ok else None
        return ok
    ad.connect = fake_connect
    ad._reconnect_delay = 0.01
    assert run(ad._ensure_connected()) is False and ad._reconnect_delay == 0.02
    assert run(ad._ensure_connected()) is True and ad._reconnect_delay == 5.0
    assert ad.stats["reconnects"] == 2
