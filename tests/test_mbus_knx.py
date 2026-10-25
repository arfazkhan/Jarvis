"""
Phase 7 — M-Bus meters and KNX (listen-only), DALI through its KNX gateway.

Real: the M-Bus and KNX sources over real sockets — a TCP server stands in for
the M-Bus gateway and a UDP endpoint for the KNX IP interface / router, each
answering per the protocol and recording every byte ARVIS sends. Scripted: the
meters' and devices' answers.
"""
import asyncio
import socket
import struct

import pytest

from agent_commercial.sources import knx_source as K
from agent_commercial.sources import mbus_source as M


# ── M-Bus frames ─────────────────────────────────────────────────────────────
def long_frame(address, data, ci=0x72, c=0x08):
    body = bytes([c, address, ci]) + data
    return bytes([0x68, len(body), len(body), 0x68]) + body + bytes([sum(body) & 0xFF, 0x16])


def header(status=0x00, medium=0x0A):
    # id 12345678 (BCD), manufacturer KAM, version, medium, access no, status, signature
    return bytes([0x78, 0x56, 0x34, 0x12, 0x2D, 0x2C, 0x19, medium, 0x01, status, 0, 0])


COOLING_RECORDS = bytes(
    [0x04, 0x06]) + (123456).to_bytes(4, "little") + bytes(          # energy, kWh
    [0x04, 0x13]) + (2500000).to_bytes(4, "little") + bytes(         # volume, litres
    [0x02, 0x2B]) + (15000).to_bytes(2, "little") + bytes(           # power, W
    [0x02, 0x3B]) + (2300).to_bytes(2, "little") + bytes(            # flow, L/h
    [0x02, 0x59]) + (650).to_bytes(2, "little") + bytes(             # flow temp, 0.01 °C
    [0x02, 0x5D]) + (1220).to_bytes(2, "little") + bytes(            # return temp
    [0x02, 0x61]) + (570).to_bytes(2, "little") + bytes(             # temperature difference, 0.01 K
    [0x44, 0x06]) + (100000).to_bytes(4, "little") + bytes(          # storage 1: last month's energy (history)
    [0x0C, 0x78, 0x11, 0x22, 0x33, 0x44,                             # fabrication number: not a value
     0x01, 0xFD, 0x17, 0x00,                                         # error flags (FD 17): not decoded
     0x0F, 0x01, 0x02])                                              # manufacturer-specific to the end


def test_a_cooling_meter_telegram_decodes_to_its_current_values():
    t = M.decode_telegram(long_frame(1, header() + COOLING_RECORDS))
    assert (t.meter_id, t.manufacturer, t.medium) == ("12345678", "KAM", 0x0A)
    assert t.skipped == 2
    assert M.current_values(t) == {"ENERGY": 123456.0, "VOLUME": 2500.0, "POWER": 15.0, "FLOW": 2.3,
                                   "FLOW_TEMP": 6.5, "RETURN_TEMP": 12.2, "TEMP_DIFF": 5.7, "STATUS_ERR": 0.0}


def test_electricity_bcd_and_extension_tables():
    recs = bytes([0x02, 0xFD, 0x48]) + (2305).to_bytes(2, "little") + bytes(   # voltage, 0.1 V
        [0x02, 0xFD, 0x59]) + (1234).to_bytes(2, "little") + bytes(            # current, mA
        [0x04, 0xFB, 0x00]) + (5).to_bytes(4, "little") + bytes(               # energy, 0.1 MWh
        [0x0C, 0x05, 0x78, 0x56, 0x34, 0x12])                                  # energy, 100 Wh, BCD 12345678
    t = M.decode_telegram(long_frame(3, recs, ci=0x78))
    assert M.current_values(t) == {"VOLTAGE": 230.5, "CURRENT": 1.234, "ENERGY": 500.0, "ENERGY_2": 1234567.8,
                                   "STATUS_ERR": 0.0}


def test_bad_frames_and_unknown_records_are_never_guessed():
    f = bytearray(long_frame(1, header() + COOLING_RECORDS))
    f[-2] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        M.decode_telegram(bytes(f))
    recs, skipped = M.decode_records(bytes([0x04, 0x86, 0x3C]) + (7).to_bytes(4, "little"))  # energy + unknown VIFE
    assert recs == [] and skipped == 1


class FakeGateway:
    """A TCP M-Bus gateway: E5 to a link reset, a telegram to REQ_UD2, silence for absent meters."""
    def __init__(self, meters):
        self.meters, self.frames = meters, []

    async def handle(self, reader, writer):
        try:
            while True:
                f = await reader.readexactly(5)
                self.frames.append(f)
                c, a = f[1], f[2]
                if a not in self.meters:
                    continue
                writer.write(b"\xE5" if c == M.SND_NKE else self.meters[a])
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()


def test_meters_are_read_over_a_tcp_gateway_and_only_asked():
    async def go():
        meters = {1: long_frame(1, header() + COOLING_RECORDS), 3: long_frame(3, header(status=0x08, medium=0x07)
                                                                                 + bytes([0x04, 0x13]) + (987654).to_bytes(4, "little"))}
        async with FakeGateway(meters) as gw:
            src = M.MBusSource({"id": "btu", "host": "127.0.0.1", "port": gw.port, "timeout": 0.3})
            cfg = {"meters": [{"address": 1, "equipment_id": "MTR-BTU-T1", "type": "cooling"},
                              {"address": 2, "equipment_id": "MTR-GONE", "type": "water"},
                              {"address": 3, "equipment_id": "MTR-W-01", "type": "water"}]}
            assert src.load_points_from_config(cfg) == 7 + 3 + 3          # declared roles + STATUS_ERR per meter
            got = []
            src.on_point_update(got.append)
            assert await src.connect()
            await src.read_all()
            return src, gw, {p.point_id: p for p in got}
    src, gw, by = asyncio.run(go())
    assert {f[1] for f in gw.frames} <= set(M.ALLOWED_C)                       # only link resets and data requests
    assert by["MTR-BTU-T1/ENERGY"].value == 123456.0 and by["MTR-BTU-T1/ENERGY"].unit == "kWh"
    assert by["MTR-BTU-T1/FLOW_TEMP"].unit == "°C" and by["MTR-BTU-T1/FLOW"].unit == "m³/h"
    assert by["MTR-BTU-T1/ENERGY"].source == "mbus:btu"
    assert not any(k.startswith("MTR-GONE") for k in by) and src.stats["reads_failed"] == 1
    assert by["MTR-W-01/STATUS_ERR"].value == 1.0                              # the meter reports an error...
    assert by["MTR-W-01/VOLUME"].quality.value == "uncertain"                  # ...so its values are marked uncertain
    assert src.stats["meters"]["MTR-BTU-T1"] == {"id": "12345678", "manufacturer": "KAM", "medium": 0x0A, "status": 0}


def test_mbus_never_sends_data_to_a_meter_and_config_is_checked():
    src = M.MBusSource({"host": "x"})
    with pytest.raises(PermissionError):
        src._send(0x53, 1)                                                     # SND_UD
    with pytest.raises(ValueError, match="type is one of"):
        M.mbus_point_entries({"meters": [{"address": 1, "equipment_id": "X", "type": "steam"}]})
    with pytest.raises(ValueError, match="primary address"):
        M.mbus_point_entries({"meters": [{"address": 251, "equipment_id": "X", "type": "water"}]})
    from agent_commercial.semantics.point_roles import parse_role
    entries = M.mbus_point_entries({"meters": [{"address": 1, "equipment_id": "B", "type": t} for t in M.METER_TYPES]})
    assert all(parse_role(e["role"]) is not None for e in entries)


# ── KNX ──────────────────────────────────────────────────────────────────────
def test_group_addresses_and_datapoint_types():
    assert K.parse_ga("1/2/3") == 0x0A03 and K.format_ga(0x0A03) == "1/2/3" and K.parse_ga("1/515") == 0x0A03
    with pytest.raises(ValueError):
        K.parse_ga("32/0/0")
    d = K.decode_dpt
    assert d("9.001", 0, b"\x0C\x1A") == 21.0 and d("9.001", 0, b"\x87\x9C") == -1.0 and d("9.001", 0, b"\x7F\xFF") is None
    assert d("5.001", 0, b"\xFF") == 100.0 and d("5.001", 0, b"\x80") == 50.2 and d("5.010", 0, b"\x80") == 128.0
    assert d("1.001", 1, b"") == 1.0 and d("7.001", 0, b"\x01\x00") == 256.0
    assert d("14.056", 0, struct.pack(">f", 412.5)) == 412.5 and d("9.001", 0, b"\x01") is None


def cemi(ga, apci=K.GROUP_WRITE, small=0, data=b"", group=True):
    tpci, lo = (apci >> 2) & 0x03, ((apci & 0x03) << 6) | (small & 0x3F)
    return bytes([K.L_DATA_IND, 0, 0xBC, 0xE0 if group else 0x60, 0x11, 0x05]) + ga.to_bytes(2, "big") + \
        bytes([1 + len(data), tpci, lo]) + data


def knx_frame(service, body):
    return struct.pack(">BBHH", 0x06, 0x10, service, 6 + len(body)) + body


def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _cfg_points():
    return {"points": [{"point_id": "RM-501/TEMP", "ga": "3/1/10", "dpt": "9.001", "unit": "°C", "role": "zone-temp"}],
            "devices": [{"template": "dali_light", "equipment_id": "LGT-L5-01",
                         "ga": {"STATUS": "1/4/3", "LEVEL": "1/2/3", "FAULT": "1/7/3"}}]}


def test_routing_listens_and_sends_nothing():
    async def go():
        port = _free_udp_port()
        src = K.KnxSource({"id": "knx", "mode": "routing", "port": port, "multicast_group": None})
        assert src.load_points_from_config(_cfg_points()) == 4                 # template: only the 3 objects with a GA
        got = []
        src.on_point_update(got.append)
        assert await src.connect()
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for c in (cemi(K.parse_ga("3/1/10"), data=b"\x0C\x1A"), cemi(K.parse_ga("1/2/3"), data=b"\xFF"),
                  cemi(K.parse_ga("1/7/3"), small=1), cemi(K.parse_ga("9/7/9"), data=b"\x01"),          # unmapped
                  cemi(K.parse_ga("1/2/3"), apci=K.GROUP_READ),                                       # a read: no value
                  cemi(0x1105, data=b"\x00", group=False)):                                           # to a device
            tx.sendto(knx_frame(K.ROUTING_INDICATION, c), ("127.0.0.1", port))
        tx.close()
        for _ in range(50):
            if len(got) >= 3 and src.stats["ignored_unmapped"]:
                break
            await asyncio.sleep(0.02)
        await src.disconnect()
        return src, {p.point_id: p.value for p in got}
    src, vals = asyncio.run(go())
    assert vals == {"RM-501/TEMP": 21.0, "LGT-L5-01/LEVEL": 100.0, "LGT-L5-01/FAULT": 1.0}
    assert src.sent == [] and src.stats["ignored_unmapped"] == 1
    with pytest.raises(PermissionError):
        src._send(K.CONNECT_REQUEST, b"")                                      # routing is receive-only


class FakeInterface(asyncio.DatagramProtocol):
    """A KNX IP interface: grants channel 7, answers heartbeats and disconnects, records everything."""
    def __init__(self, refuse=False):
        self.got, self.client, self.refuse = [], None, refuse

    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        service, body = (data[2] << 8) | data[3], data[6:]
        self.got.append((service, body))
        self.client = addr
        if service == K.CONNECT_REQUEST:
            status = 0x24 if self.refuse else 0
            self.t.sendto(knx_frame(K.CONNECT_RESPONSE, bytes([7, status]) + K._hpai("127.0.0.1", 3671)
                                    + bytes([4, 4, 0x11, 0x05])), addr)
        elif service == K.CONNECTIONSTATE_REQUEST:
            self.t.sendto(knx_frame(K.CONNECTIONSTATE_RESPONSE, bytes([body[0], 0])), addr)
        elif service == K.DISCONNECT_REQUEST:
            self.t.sendto(knx_frame(K.DISCONNECT_RESPONSE, bytes([body[0], 0])), addr)

    def tunnel(self, channel, seq, c):
        self.t.sendto(knx_frame(K.TUNNELLING_REQUEST, bytes([4, channel, seq, 0]) + c), self.client)


def test_tunnelling_only_keeps_the_tunnel_open():
    async def go():
        loop = asyncio.get_running_loop()
        t, iface = await loop.create_datagram_endpoint(FakeInterface, local_addr=("127.0.0.1", 0))
        port = t.get_extra_info("sockname")[1]
        src = K.KnxSource({"id": "knx", "mode": "tunnelling", "host": "127.0.0.1", "port": port,
                           "local_ip": "127.0.0.1", "heartbeat_s": 0.05, "timeout": 1})
        src.load_points_from_config(_cfg_points())
        got = []
        src.on_point_update(got.append)
        assert await src.connect() and src._channel == 7
        await src.start_polling()
        level = cemi(K.parse_ga("1/2/3"), data=b"\x80")
        iface.tunnel(7, 0, level)
        iface.tunnel(7, 0, level)                                              # the interface repeats (lost ack)
        iface.tunnel(9, 1, level)                                              # someone else's channel
        iface.tunnel(7, 1, cemi(K.parse_ga("3/1/10"), data=b"\x87\x9C"))
        await asyncio.sleep(0.3)                                               # a few heartbeats
        await src.disconnect()
        t.close()
        return src, iface, [(p.point_id, p.value) for p in got]
    src, iface, got = asyncio.run(go())
    assert got == [("LGT-L5-01/LEVEL", 50.2), ("RM-501/TEMP", -1.0)]           # the repeat is not a second reading
    services = [s for s, _ in iface.got]
    assert set(services) <= set(K.ALLOWED_TO_SEND) and K.TUNNELLING_REQUEST not in services
    acks = [b for s, b in iface.got if s == K.TUNNELLING_ACK]
    assert [(b[1], b[2]) for b in acks] == [(7, 0), (7, 0), (7, 1)]           # every request on our channel acked
    assert services.count(K.CONNECTIONSTATE_REQUEST) >= 2 and services[-1] == K.DISCONNECT_REQUEST
    with pytest.raises(PermissionError):
        src._send(K.TUNNELLING_REQUEST, b"")


def test_an_interface_with_no_free_tunnel_is_reported():
    async def go():
        loop = asyncio.get_running_loop()
        t, _ = await loop.create_datagram_endpoint(lambda: FakeInterface(refuse=True), local_addr=("127.0.0.1", 0))
        src = K.KnxSource({"mode": "tunnelling", "host": "127.0.0.1", "port": t.get_extra_info("sockname")[1],
                           "local_ip": "127.0.0.1", "timeout": 1})
        ok = await src.connect()
        await src.disconnect()
        t.close()
        return ok
    assert asyncio.run(go()) is False


def test_templates_quiet_devices_and_coverage():
    with pytest.raises(ValueError, match="not in template"):
        K.expand_devices([{"template": "dali_light", "equipment_id": "L", "ga": {"BRIGHTNESS": "1/1/1"}}])
    with pytest.raises(ValueError, match="DPT 3.007 not supported"):
        K.KnxSource({}).load_points_from_config({"points": [{"point_id": "X/Y", "ga": "1/1/1", "dpt": "3.007"}]})
    fault = [e for e in K.knx_point_entries(_cfg_points()) if e["point_id"] == "LGT-L5-01/FAULT"][0]
    assert fault["alarm_when"]["op"] == "==" and fault["role"] == "fault-status"

    src = K.KnxSource({"mode": "routing"})
    src.load_points_from_config({"devices": [{"template": "room_climate", "equipment_id": "FCU-501",
                                              "ga": {"TEMP": "3/1/10"}}]})
    got = []
    src.on_point_update(got.append)
    src._telegram(cemi(K.parse_ga("3/1/10"), data=b"\x0C\x1A"))
    src._freshness._last_ok["FCU-501/TEMP"] -= 3601                           # an hour of silence from a cyclic sender
    assert asyncio.run(src.check()) == ["FCU-501/TEMP"]
    assert got[-1].quality.value == "stale" and got[-1].value == 21.0

    from agent_commercial.coverage import load_catalog
    from agent_commercial.semantics.point_roles import equipment_kind, parse_role
    assert equipment_kind(None, "LGT-L5-01") == "lighting" and "lighting" in load_catalog()["kinds"]
    for t in ("dali_light", "room_climate"):
        for e in K.expand_devices([{"template": t, "equipment_id": "E", "ga": {}}]):
            assert e.get("role") is None or parse_role(e["role"]) is not None
