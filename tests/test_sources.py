"""
Phase 0 — many data sources at once.

Real: SourceManager + registry, OpsCopilot's wiring (_start_sources, _wire_adapter,
_on_point_update) into a real BMSStateEngine, the TelemetryRecorder into a real
BMSDatabase, monitoring_health's classification. Scripted: the data source itself
(a fake transport registered as its own kind), never the parts under test.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_commercial.bms_data_model import BMSDataPoint, PointQuality
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.sources import KINDS, DataSource, SourceManager, register_source


class ScriptedSource:
    """A data source whose transport is a script: it 'reads' fixed values."""
    def __init__(self, cfg):
        self.cfg, self.points, self.cbs = cfg, [], []
        self.is_connected = False
        self.polling = False
        self.writes = 0                                  # a source must never write

    def load_points_from_config(self, config):
        self.points = list(config.get("points") or [])
        return len(self.points)

    async def connect(self):
        self.is_connected = not self.cfg.get("unreachable")
        return self.is_connected

    async def disconnect(self):
        self.is_connected = False

    async def start_polling(self, interval_seconds=30):
        self.polling = True
        if self.is_connected:
            for p in self.points:
                pt = BMSDataPoint(point_id=p["point_id"], name=p["point_id"], value=p["value"], unit=p.get("unit", ""),
                                  equipment_id=p["point_id"].split("/")[0], source=f"scripted:{self.cfg['id']}")
                for cb in self.cbs:
                    cb(pt)

    async def stop_polling(self):
        self.polling = False

    def on_point_update(self, cb):
        self.cbs.append(cb)

    def get_stats(self):
        return {"is_connected": self.is_connected, "polling_active": self.polling, "stale_points": [],
                "points_configured": len(self.points)}


register_source("scripted", build=ScriptedSource, points_config=lambda cfg: cfg,
                point_entries=lambda cfg: list(cfg.get("points") or []))


def _ops():
    """OpsCopilot's own wiring methods on a minimal instance with a real state engine."""
    from agent_commercial.main import OpsCopilot
    ns = SimpleNamespace(state_engine=BMSStateEngine(), data_source="UNAVAILABLE", _bms_connected=False,
                         predictive_engine=SimpleNamespace(filter_predictor=SimpleNamespace(record_reading=lambda **k: None)),
                         energy_analyzer=None, water_adapter=None, source_manager=SourceManager(),
                         bacnet_adapter=None, modbus_adapter=None, opcua_adapter=None, mode="multi")
    ns._ingest_meter_point = lambda p: None
    ns._on_point_update = lambda p: OpsCopilot._on_point_update(ns, p)
    ns._wire_adapter = lambda a: OpsCopilot._wire_adapter(ns, a)
    return ns


def _src(sid, *points, **kw):
    return {"id": sid, "kind": "scripted", "points": [{"point_id": p, "value": v} for p, v in points], **kw}


# ── the shape ────────────────────────────────────────────────────────────────
def test_the_three_existing_adapters_already_are_data_sources():
    from agent_commercial.modbus_adapter import ModbusAdapter
    assert isinstance(ModbusAdapter(host="127.0.0.1"), DataSource)
    assert isinstance(ScriptedSource({}), DataSource)
    for kind in ("bacnet", "modbus", "opcua"):
        assert kind in KINDS                                    # registered, lazily imported


def test_site_config_sources_list_is_normalised(tmp_path):
    from agent_commercial.main import build_sources
    srcs = build_sources({"sources": [
        {"kind": "bacnet", "local_address": "10.0.0.5", "points": [{"point_id": "AHU-01/SAT", "device_id": 1,
                                                                     "object_type": "analogInput", "object_instance": 1}]},
        {"kind": "modbus", "host": "10.0.0.20", "required": False, "registers": []},
        {"kind": "modbus", "id": "genset", "host": "10.0.0.21", "registers": []},
    ]}, base_dir=str(tmp_path))
    assert [s["id"] for s in srcs] == ["bacnet", "modbus", "genset"]
    assert srcs[0]["points_config"]["points"][0]["point_id"] == "AHU-01/SAT" and srcs[0]["local_address"] == "10.0.0.5"
    assert srcs[1]["required"] is False
    assert build_sources({"bacnet": {"points": []}}) == []           # the old single-protocol form: no sources
    with pytest.raises(ValueError, match="needs a kind"):
        build_sources({"sources": [{"id": "x"}]})


# ── running several at once ──────────────────────────────────────────────────
def test_two_sources_feed_one_building():
    from agent_commercial.main import OpsCopilot
    ops = _ops()
    ops.sources_config = [_src("bms", ("AHU-01/SAT", 13.2), ("AHU-01/RAT", 24.0)),
                          _src("meters", ("MTR-01/KW", 412.0))]
    asyncio.run(OpsCopilot._start_sources(ops))
    pts = ops.state_engine._points
    assert {"AHU-01/SAT", "AHU-01/RAT", "MTR-01/KW"} <= set(pts)
    assert pts["MTR-01/KW"].source == "scripted:meters"
    assert ops.data_source == "LIVE" and ops._bms_connected
    assert [s["id"] for s in ops.source_manager.stats()] == ["bms", "meters"]
    assert all(h.adapter.writes == 0 for h in ops.source_manager.handles)


def test_an_optional_source_down_does_not_stop_the_building():
    from agent_commercial.main import OpsCopilot
    ops = _ops()
    ops.sources_config = [_src("bms", ("AHU-01/SAT", 13.2)), _src("solar", ("PV-01/KW", 80.0), required=False, unreachable=True)]
    asyncio.run(OpsCopilot._start_sources(ops))
    assert "AHU-01/SAT" in ops.state_engine._points and "PV-01/KW" not in ops.state_engine._points
    assert [(s["id"], s["is_connected"]) for s in ops.source_manager.stats()] == [("bms", True), ("solar", False)]


def test_a_required_source_down_stops_startup_unless_allowed_offline():
    from agent_commercial.main import OpsCopilot
    ops = _ops()
    ops.sources_config = [_src("bms", ("AHU-01/SAT", 13.2), unreachable=True)]
    with pytest.raises(RuntimeError, match="could not connect"):
        asyncio.run(OpsCopilot._start_sources(ops))
    ops = _ops()
    ops.sources_config = [_src("bms", ("AHU-01/SAT", 13.2), unreachable=True, allow_offline=True)]
    asyncio.run(OpsCopilot._start_sources(ops))
    assert ops.data_source == "UNAVAILABLE" and not ops._bms_connected   # degraded: no data, never made-up data


def test_production_refuses_a_source_with_no_points(monkeypatch):
    monkeypatch.setenv("ARVIS_ENV", "production")
    mgr = SourceManager()
    with pytest.raises(RuntimeError, match="no points configured"):
        asyncio.run(mgr.start([_src("bms")], _ops()))


def test_unknown_kinds_and_duplicate_ids_are_rejected():
    with pytest.raises(RuntimeError, match="unknown kind"):
        asyncio.run(SourceManager().start([{"id": "x", "kind": "telepathy"}], _ops()))
    with pytest.raises(RuntimeError, match="used twice"):
        asyncio.run(SourceManager().start([_src("a", ("X/Y", 1.0)), _src("a", ("X/Z", 1.0))], _ops()))


def test_roles_come_from_every_sources_points():
    from agent_commercial.main import OpsCopilot
    ns = SimpleNamespace(state_engine=BMSStateEngine(), bacnet_config={}, modbus_config={}, opcua_config={},
                         sources_config=[{"id": "m", "kind": "scripted",
                                          "points": [{"point_id": "AHU-09/SAT", "value": 1, "role": "supply-air-temp", "unit": "°C"}]}])
    assert OpsCopilot._register_config_roles(ns) == 1


# ── monitoring sees every source ─────────────────────────────────────────────
def _health(ops):
    from agent_commercial.monitoring_health import MonitoringHealthWatcher, assess_monitoring
    w = MonitoringHealthWatcher(ops, publish=lambda *a: None)
    return w._classify(assess_monitoring(ops, 15, datetime.now(timezone.utc)))


def test_optional_source_down_is_degraded_required_down_is_blind():
    from agent_commercial.main import OpsCopilot
    ops = _ops()
    ops.sources_config = [_src("bms", ("AHU-01/SAT", 13.2)), _src("solar", ("PV-01/KW", 80.0), required=False)]
    asyncio.run(OpsCopilot._start_sources(ops))
    assert _health(ops) == "ok"
    ops.source_manager.handles[1].adapter.is_connected = False
    assert _health(ops) == "degraded"                  # solar is out; the building is still seen
    ops.source_manager.handles[0].adapter.is_connected = False
    assert _health(ops) == "blind"                     # the BMS is out: lost sight of the building


def test_legacy_single_adapter_monitoring_is_unchanged():
    ad = ScriptedSource({"id": "x"}); ad.is_connected = True
    ops = SimpleNamespace(state_engine=BMSStateEngine(), bacnet_adapter=ad, modbus_adapter=None, opcua_adapter=None,
                          mode="bacnet", source_manager=SourceManager())
    asyncio.run(ops.state_engine.update_point(BMSDataPoint(point_id="AHU-01/SAT", name="SAT", value=13.0, source="bacnet")))
    assert _health(ops) == "ok"
    ad.is_connected = False
    assert _health(ops) == "blind"


# ── provenance: every stored reading says where it came from ────────────────
def test_source_and_confidence_are_stored_and_old_databases_migrate(tmp_path):
    import sqlite3
    from agent_commercial.database import BMSDatabase
    from agent_commercial.telemetry_recorder import TelemetryRecorder
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)                          # a database from before provenance existed
    con.execute("CREATE TABLE data_points (point_id TEXT, equipment_id TEXT, value REAL, unit TEXT, "
                "quality TEXT DEFAULT 'good', timestamp TEXT, PRIMARY KEY (point_id, timestamp))")
    con.execute("INSERT INTO data_points VALUES ('AHU-01/SAT','AHU-01',13.0,'°C','good','2026-10-01T10:00:00')")
    con.commit(); con.close()

    async def go():
        db = BMSDatabase(db_path=str(path))
        rec = TelemetryRecorder(db)
        rec.on_point(BMSDataPoint(point_id="TANK-1/LVL", name="Tank level", value=62.0, unit="%",
                                  equipment_id="TANK-1", source="manual", confidence=.9))
        rec.on_point(BMSDataPoint(point_id="MTR-01/KW", name="kW", value=410.0, unit="kW", source="modbus:meters"))
        await rec.flush()
        conn = await db._get_async_connection()
        async with conn.execute("SELECT point_id, source, confidence FROM data_points ORDER BY point_id") as cur:
            rows = [tuple(r) for r in await cur.fetchall()]
        await db.close()
        return rows
    rows = asyncio.run(go())
    assert ("AHU-01/SAT", None, None) in rows                           # old rows survive
    assert ("TANK-1/LVL", "manual", .9) in rows and ("MTR-01/KW", "modbus:meters", 1.0) in rows


def test_a_manual_value_never_overrides_a_fresh_live_reading():
    async def go():
        se = BMSStateEngine()
        now = datetime.now()
        await se.update_point(BMSDataPoint(point_id="P-1/DP", name="dp", value=210.0, source="bacnet", timestamp=now))
        await se.update_point(BMSDataPoint(point_id="P-1/DP", name="dp", value=180.0, source="manual",
                                           timestamp=now + timedelta(seconds=30)))
        fresh_kept = se._points["P-1/DP"].value
        se._points["P-1/DP"].timestamp = now - timedelta(hours=2)       # the live feed went quiet
        await se.update_point(BMSDataPoint(point_id="P-1/DP", name="dp", value=180.0, source="manual", timestamp=now))
        return fresh_kept, se._points["P-1/DP"].value
    assert asyncio.run(go()) == (210.0, 180.0)
