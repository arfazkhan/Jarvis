"""
OPC UA adapter — against a real OPC UA server, not mocks.

asyncua ships a server implementation, so each test starts a genuine OPC UA
server on localhost with a small AHU address space, and the adapter talks to
it over opc.tcp exactly as it would to a BMS gateway on site. (Test code writes
values on its OWN server to set up scenarios; the runtime adapter never writes,
which test_deployment_security enforces.)
"""
import asyncio
import socket

import pytest
import pytest_asyncio

asyncua = pytest.importorskip("asyncua")
from asyncua import Server, ua  # noqa: E402

from agent_commercial.bms_data_model import PointQuality  # noqa: E402
from agent_commercial.opcua_adapter import (  # noqa: E402
    OpcUaAdapter, OpcUaPoint, opcua_adapter_from_config,
)

NS_URI = "urn:arvis:test:bms"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_server(port: int, pad_namespaces: int = 0):
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://127.0.0.1:{port}/arvis/")
    # Extra namespaces registered first shift our namespace's INDEX — like a
    # gateway that was reconfigured — while its URI stays the same.
    for i in range(pad_namespaces):
        await server.register_namespace(f"urn:other:{i}")
    idx = await server.register_namespace(NS_URI)
    ahu = await server.nodes.objects.add_object(idx, "AHU-03")
    v = {
        "sat": await ahu.add_variable(f"ns={idx};s=AHU-03.SAT", "SupplyAirTemp", 13.5),
        "fan": await ahu.add_variable(f"ns={idx};s=AHU-03.FanStatus", "FanStatus", True),
        "hours": await ahu.add_variable(f"ns={idx};s=AHU-03.RunHours", "RunHours", 4210),
        "label": await ahu.add_variable(f"ns={idx};s=AHU-03.Label", "Label", "Level 3 west"),
        "rh": await ahu.add_variable(f"ns={idx};s=AHU-03.RH", "ReturnHumidity", 55.0),
    }
    await v["sat"].add_property(0, "EngineeringUnits", ua.EUInformation(
        NamespaceUri="http://www.opcfoundation.org/UA/units/un/cefact",
        UnitId=4408652, DisplayName=ua.LocalizedText("°C"), Description=ua.LocalizedText("degree Celsius")))
    await server.start()
    return server, idx, v


@pytest_asyncio.fixture
async def site():
    port = _free_port()
    server, idx, v = await _start_server(port)
    yield {"server": server, "idx": idx, "vars": v, "port": port,
           "endpoint": f"opc.tcp://127.0.0.1:{port}/arvis/"}
    try:
        await server.stop()
    except Exception:
        pass


def _points(scale=1.0):
    return {"points": [
        {"node_id": f"nsu={NS_URI};s=AHU-03.SAT", "point_id": "AHU-03/SAT", "equipment_id": "AHU-03",
         "unit": "°C", "scale": scale},
        {"node_id": f"nsu={NS_URI};s=AHU-03.FanStatus", "point_id": "AHU-03/FAN", "point_type": "status"},
        {"node_id": f"nsu={NS_URI};s=AHU-03.RunHours", "point_id": "AHU-03/HRS", "point_type": "counter"},
        {"node_id": f"nsu={NS_URI};s=AHU-03.Label", "point_id": "AHU-03/LABEL"},
    ]}


async def _adapter(endpoint, cfg=None):
    ad = OpcUaAdapter(endpoint, timeout=3)
    ad.load_points_from_config(cfg or _points())
    assert await ad.connect()
    return ad


# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reads_numbers_bools_and_ints_and_skips_strings(site):
    ad = await _adapter(site["endpoint"])
    try:
        got = {dp.point_id: dp for dp in await ad.read_all_points()}
        assert got["AHU-03/SAT"].value == pytest.approx(13.5)
        assert got["AHU-03/SAT"].quality == PointQuality.GOOD and got["AHU-03/SAT"].source == "opcua"
        assert got["AHU-03/FAN"].value == 1.0                   # boolean status → 1/0
        assert got["AHU-03/HRS"].value == 4210.0
        assert "AHU-03/LABEL" not in got                        # a string is not a reading
        assert ad.get_stats()["reads_success"] == 3
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_scaling_applies(site):
    ad = await _adapter(site["endpoint"], _points(scale=10.0))
    try:
        got = {dp.point_id: dp.value for dp in await ad.read_all_points()}
        assert got["AHU-03/SAT"] == pytest.approx(135.0)
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_bad_status_is_not_ingested_and_uncertain_is_flagged(site):
    v = site["vars"]
    await v["sat"].write_value(ua.DataValue(Value=ua.Variant(99.0, ua.VariantType.Double),
                                            StatusCode=ua.StatusCode(ua.StatusCodes.BadSensorFailure)))
    await v["hours"].write_value(ua.DataValue(Value=ua.Variant(4300, ua.VariantType.Int64),
                                              StatusCode=ua.StatusCode(ua.StatusCodes.UncertainLastUsableValue)))
    ad = await _adapter(site["endpoint"])
    try:
        got = {dp.point_id: dp for dp in await ad.read_all_points()}
        assert "AHU-03/SAT" not in got                          # failed sensor: no fake value
        assert got["AHU-03/HRS"].quality == PointQuality.UNCERTAIN
        assert ad.get_stats()["reads_uncertain"] == 1
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_namespace_uri_survives_index_renumbering():
    """The gateway is reconfigured and our namespace moves from index 2 to 5.
    URI-form node ids still read the right variable."""
    port = _free_port()
    server, idx, _ = await _start_server(port, pad_namespaces=3)
    try:
        assert idx >= 4
        ad = await _adapter(f"opc.tcp://127.0.0.1:{port}/arvis/")
        got = {dp.point_id: dp.value for dp in await ad.read_all_points()}
        assert got["AHU-03/SAT"] == pytest.approx(13.5)
        await ad.disconnect()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_unknown_namespace_or_node_is_reported_not_guessed(site):
    cfg = {"points": [
        {"node_id": "nsu=urn:not:there;s=X", "point_id": "P/NS"},
        {"node_id": f"nsu={NS_URI};s=AHU-03.DoesNotExist", "point_id": "P/MISSING"},
        {"node_id": f"nsu={NS_URI};s=AHU-03.SAT", "point_id": "P/OK"},
    ]}
    ad = await _adapter(site["endpoint"], cfg)
    try:
        got = {dp.point_id for dp in await ad.read_all_points()}
        assert got == {"P/OK"}
        assert "P/NS" in ad.get_stats()["points_unresolved"]
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_server_loss_goes_stale_then_recovers_on_reconnect(site):
    ad = await _adapter(site["endpoint"])
    try:
        await ad.read_all_points()
        await site["server"].stop()
        assert [dp for dp in await ad.read_all_points() if dp.quality == PointQuality.GOOD] == []
        assert ad.is_connected is False                         # session marked dead → reconnect next tick
        # Age the points past their stale timeout: last value is emitted once, flagged STALE.
        for pid in list(ad._freshness._last_ok):
            ad._freshness._last_ok[pid] -= 1000
        stale = {dp.point_id: dp for dp in await ad.read_all_points()}
        assert stale["AHU-03/SAT"].quality == PointQuality.STALE and stale["AHU-03/SAT"].value == pytest.approx(13.5)

        # The gateway comes back on the same endpoint; the adapter reconnects and reads live again.
        server2, _, _ = await _start_server(site["port"])
        site["server"] = server2
        assert await ad._ensure_connected()
        got = {dp.point_id: dp for dp in await ad.read_all_points()}
        assert got["AHU-03/SAT"].quality == PointQuality.GOOD
        # Recovered points leave STALE; the string point never gave a number, so it stays flagged.
        assert ad.get_stats()["stale_points"] == ["AHU-03/LABEL"]
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_batches_respect_server_read_limit(site):
    ad = OpcUaAdapter(site["endpoint"], timeout=3, max_per_request=1)
    ad.load_points_from_config(_points())
    assert await ad.connect()
    try:
        got = {dp.point_id for dp in await ad.read_all_points()}
        assert got == {"AHU-03/SAT", "AHU-03/FAN", "AHU-03/HRS"}
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_discovery_browses_variables_with_stable_ids_and_units(site):
    ad = await _adapter(site["endpoint"], {"points": []})
    try:
        found = {d["point_name"]: d for d in await ad.discover_variables()}
        sat = found["SupplyAirTemp"]
        assert sat["node_id"] == f"nsu={NS_URI};s=AHU-03.SAT"   # URI form, survives renumbering
        assert sat["browse_path"] == "AHU-03/SupplyAirTemp"
        assert sat["unit"] == "°C" and sat["data_type"] == "Double"
        assert "ServerStatus" not in found                      # server diagnostics skipped
        # A discovered entry is directly usable as a point config.
        ad2 = await _adapter(site["endpoint"], {"points": [dict(sat, point_id="AHU-03/SAT")]})
        assert (await ad2.read_all_points())[0].value == pytest.approx(13.5)
        await ad2.disconnect()
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_polling_feeds_the_callback(site):
    ad = await _adapter(site["endpoint"])
    seen = []
    ad.on_point_update(seen.append)
    try:
        await ad.start_polling(interval_seconds=1)
        for _ in range(50):
            if len(seen) >= 3:
                break
            await asyncio.sleep(0.1)
        assert {dp.point_id for dp in seen} >= {"AHU-03/SAT", "AHU-03/FAN", "AHU-03/HRS"}
    finally:
        await ad.disconnect()


@pytest.mark.asyncio
async def test_unreachable_endpoint_fails_cleanly():
    ad = OpcUaAdapter(f"opc.tcp://127.0.0.1:{_free_port()}/nothing/", timeout=1)
    assert await ad.connect() is False
    assert ad.is_connected is False


# ── config ───────────────────────────────────────────────────────────────────
def test_credentials_are_refused_in_the_config_file():
    with pytest.raises(ValueError, match="ARVIS_OPCUA_PASSWORD"):
        opcua_adapter_from_config({"endpoint": "opc.tcp://10.0.0.5:4840", "password": "x"})
    with pytest.raises(ValueError, match="endpoint"):
        opcua_adapter_from_config({})


def test_credentials_come_from_env(monkeypatch):
    monkeypatch.setenv("ARVIS_OPCUA_USERNAME", "arvis_ro")
    monkeypatch.setenv("ARVIS_OPCUA_PASSWORD", "s3cret")
    ad = opcua_adapter_from_config({"endpoint": "opc.tcp://10.0.0.5:4840"})
    assert ad._username == "arvis_ro" and ad._password == "s3cret"


def test_invalid_point_config_is_skipped():
    ad = OpcUaAdapter("opc.tcp://10.0.0.5:4840")
    n = ad.load_points_from_config({"points": [{"point_id": "no-node"}, {"node_id": "ns=2;s=A", "point_id": "A",
                                                                          "point_type": "nonsense"},
                                               {"node_id": "ns=2;s=B", "point_id": "B"}]})
    assert n == 1


def test_number_conversion():
    p = OpcUaPoint(node_id="ns=2;s=X", point_id="X", scale=0.1, offset=-40)
    assert p.to_number(500) == pytest.approx(10.0)
    assert p.to_number(False) == pytest.approx(-40.0)
    assert p.to_number(float("nan")) is None and p.to_number("12") is None and p.to_number([1, 2]) is None


@pytest.mark.asyncio
async def test_copilot_opcua_mode_ingests_live_points(site, monkeypatch):
    """End to end through OpsCopilot: mode=opcua connects, wires, and the first
    GOOD reading makes the building LIVE."""
    from agent_commercial.main import OpsCopilot
    cfg = dict(_points(), endpoint=site["endpoint"], poll_interval=1)
    cp = OpsCopilot.__new__(OpsCopilot)       # only the pieces _start_opcua needs
    cp.opcua_config = cfg
    cp.opcua_adapter = None
    cp.data_source = "UNAVAILABLE"
    received = []
    cp._on_point_update = received.append
    await OpsCopilot._start_opcua(cp)
    try:
        for _ in range(50):
            if any(dp.point_id == "AHU-03/SAT" for dp in received):
                break
            await asyncio.sleep(0.1)
        assert cp._bms_connected is True
        assert any(dp.point_id == "AHU-03/SAT" and dp.value == pytest.approx(13.5) for dp in received)
    finally:
        await cp.opcua_adapter.disconnect()


@pytest.mark.asyncio
async def test_copilot_opcua_mode_refuses_to_start_on_a_dead_endpoint():
    from agent_commercial.main import OpsCopilot
    cp = OpsCopilot.__new__(OpsCopilot)
    cp.opcua_config = {"endpoint": f"opc.tcp://127.0.0.1:{_free_port()}/x/", "timeout": 1, "points": []}
    cp.opcua_adapter = None
    cp.data_source = "UNAVAILABLE"
    with pytest.raises(RuntimeError, match="allow_offline"):
        await OpsCopilot._start_opcua(cp)
