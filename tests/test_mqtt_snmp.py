"""
Phase 4 — MQTT (+ LoRaWAN presets) and SNMP.

Real: an MQTT broker (amqtt, in-process) and aiomqtt on both ends — the test
publishes like a LoRaWAN network server would, ARVIS only subscribes; pysnmp
against a port nobody answers on; the templates; the sources registry. Scripted:
the SNMP agent (its answers, at the source's transport seam).
"""
import asyncio
import json
import socket
import sys

import pytest

from agent_commercial.bms_data_model import PointQuality
from agent_commercial.sources.common import json_path, number, timestamp


def _selector_loop():
    # paho-mqtt (under aiomqtt) needs add_reader: the selector loop, as on the Linux site box.
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ── the small parts ─────────────────────────────────────────────────────────
def test_json_paths_numbers_and_times():
    doc = {"object": {"level": 62.5, "pump": "ON"}, "values": [3, 4], "time": "2026-10-25T09:00:00Z"}
    assert json_path(doc, "$.object.level") == 62.5 and json_path(doc, "$.values[1]") == 4
    assert json_path(doc, "$.object.nope") is None and json_path(doc, "$.values[9]") is None
    assert number("ON") == 1.0 and number(True) == 1.0 and number("4.2") == 4.2 and number("n/a") is None
    assert timestamp("2026-10-25T09:00:00Z").isoformat() == "2026-10-25T09:00:00+00:00"
    assert timestamp(1761382800000).year == 2025


def test_topic_wildcards_and_lorawan_presets():
    from agent_commercial.sources.mqtt_source import point_from_config, topic_matches
    assert topic_matches("application/+/device/abc/event/up", "application/7/device/abc/event/up")
    assert not topic_matches("application/+/device/abc/event/up", "application/7/device/xyz/event/up")
    assert topic_matches("plant/#", "plant/chwp1/current") and not topic_matches("plant/+", "plant/a/b")
    cs = point_from_config({"point_id": "TANK-1/LVL", "preset": "chirpstack", "device": "a840", "field": "level"})
    assert (cs.topic, cs.value, cs.ts) == ("application/+/device/a840/event/up", "$.object.level", "$.time")
    ttn = point_from_config({"point_id": "LEAK-1/WET", "preset": "ttn", "device": "leak-b2", "field": "water_leak"})
    assert ttn.value == "$.uplink_message.decoded_payload.water_leak"
    with pytest.raises(ValueError, match="needs device and field"):
        point_from_config({"point_id": "X/Y", "preset": "ttn"})


def test_secrets_never_live_in_the_config(monkeypatch):
    from agent_commercial.sources.mqtt_source import MqttSource
    with pytest.raises(ValueError, match="password_env"):
        MqttSource({"id": "iot", "password": "hunter2"})
    with pytest.raises(ValueError, match="ARVIS_MQTT_PW .* is not set"):
        MqttSource({"id": "iot", "password_env": "ARVIS_MQTT_PW"})
    monkeypatch.setenv("ARVIS_MQTT_PW", "s3cret")
    assert MqttSource({"id": "iot", "password_env": "ARVIS_MQTT_PW"}).password == "s3cret"


# ── MQTT end to end, through a real broker ───────────────────────────────────
def test_lorawan_and_plain_sensors_arrive_through_a_real_broker():
    amqtt = pytest.importorskip("amqtt.broker")
    import aiomqtt
    from agent_commercial.sources.mqtt_source import MqttSource
    port = _free_port()

    async def go():
        broker = amqtt.Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                               "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}})
        await broker.start()
        got = []
        src = MqttSource({"id": "iot", "host": "127.0.0.1", "port": port})
        src.load_points_from_config({"points": [
            {"point_id": "TANK-1/LVL", "preset": "chirpstack", "device": "a84041000181c45b", "field": "level", "unit": "%"},
            {"point_id": "CHWP-1/AMPS", "topic": "plant/chwp1/current", "value": "$.amps", "unit": "A"},
            {"point_id": "FP-1/RUN", "topic": "plant/fp1/run"},
        ]})
        src.on_point_update(got.append)
        assert await src.connect() is True
        await src.start_polling()
        for _ in range(50):
            if src.is_connected and src.stats["messages"] == 0 and src._task and not src._task.done():
                break
            await asyncio.sleep(.05)
        await asyncio.sleep(.3)                                   # let the subscriptions land
        async with aiomqtt.Client(hostname="127.0.0.1", port=port, identifier="lns") as lns:   # the network server
            await lns.publish("application/3/device/a84041000181c45b/event/up",
                              json.dumps({"time": "2026-10-25T09:00:00Z", "object": {"level": 62.5, "battery": 3.6}}))
            await lns.publish("plant/chwp1/current", json.dumps({"amps": 41.2}))
            await lns.publish("plant/fp1/run", "ON")
            await lns.publish("plant/chwp1/current", json.dumps({"amps": "n/a"}))     # garbage: no reading
        for _ in range(60):
            if len(got) >= 3 and src.stats["unparsed"] >= 1:
                break
            await asyncio.sleep(.05)
        stats = src.get_stats()
        await src.disconnect()
        await broker.shutdown()
        return got, stats

    loop = _selector_loop()
    try:
        got, stats = loop.run_until_complete(go())
    finally:
        loop.close()
    by = {p.point_id: p for p in got}
    assert by["TANK-1/LVL"].value == 62.5 and by["TANK-1/LVL"].timestamp.isoformat() == "2026-10-25T09:00:00+00:00"
    assert by["CHWP-1/AMPS"].value == 41.2 and by["FP-1/RUN"].value == 1.0
    assert all(p.source == "mqtt:iot" for p in got)
    assert stats["unparsed"] == 1 and stats["messages"] == 4


def test_a_silent_sensor_goes_stale_once_with_its_last_value():
    from agent_commercial.sources.mqtt_source import MqttSource

    async def go():
        got = []
        src = MqttSource({"id": "iot", "stale_after_s": 0.1})
        src.load_points_from_config({"points": [{"point_id": "COLD-1/TEMP", "topic": "k/cold1", "value": "$.t"}]})
        src.on_point_update(got.append)
        await src.handle("k/cold1", b'{"t": -18.5}')
        task = asyncio.create_task(src._watch_stale(0.05))
        await asyncio.sleep(1.4)                          # PointFreshness floors a timeout at 1 s
        task.cancel()
        return got
    got = asyncio.run(go())
    assert [(p.value, p.quality) for p in got] == [(-18.5, PointQuality.GOOD), (-18.5, PointQuality.STALE)]


def test_mqtt_runs_alongside_other_sources():
    from agent_commercial.sources import KINDS
    from agent_commercial.sources.mqtt_source import MqttSource
    adapter = KINDS["mqtt"].build({"id": "iot", "points": [{"point_id": "A/B", "topic": "x"}]})
    assert isinstance(adapter, MqttSource)
    assert KINDS["mqtt"].point_entries({"points": [{"point_id": "A/B", "topic": "x", "role": "equipment-temp"}]})[0]["role"]


# ── SNMP ─────────────────────────────────────────────────────────────────────
def test_the_ups_template_expands_into_named_scaled_points(monkeypatch):
    from agent_commercial.sources.snmp_source import SnmpSource, snmp_point_entries
    entries = snmp_point_entries({"devices": [{"template": "ups_mib", "equipment_id": "UPS-1"}]})
    by = {e["point_id"]: e for e in entries}
    assert by["UPS-1/BATT_PCT"]["oid"] == "1.3.6.1.2.1.33.1.2.4.0" and by["UPS-1/BATT_PCT"]["role"] == "battery-charge"
    assert by["UPS-1/ALARMS"]["alarm_when"]["op"] == ">"

    monkeypatch.setenv("ARVIS_SNMP_COMMUNITY", "plantro")
    src = SnmpSource({"id": "ups", "host": "10.10.0.30", "community_env": "ARVIS_SNMP_COMMUNITY"})
    src.load_points_from_config({"devices": [{"template": "ups_mib", "equipment_id": "UPS-1"}]})
    answers = {"1.3.6.1.2.1.33.1.2.4.0": 97, "1.3.6.1.2.1.33.1.2.5.0": 545, "1.3.6.1.2.1.33.1.4.4.1.5.1": 38,
               "1.3.6.1.2.1.33.1.6.1.0": 0}

    async def agent(oids):                                        # the UPS, at the transport seam
        return {o: answers[o] for o in oids if o in answers}
    src.get = agent
    got = []
    src.on_point_update(got.append)
    assert asyncio.run(src.read_all()) == 4
    vals = {p.point_id: p.value for p in got}
    assert vals == {"UPS-1/BATT_PCT": 97.0, "UPS-1/BATT_V": pytest.approx(54.5), "UPS-1/LOAD_PCT": 38.0,
                    "UPS-1/ALARMS": 0.0}
    assert {p.source for p in got} == {"snmp:ups"}


def test_snmp_community_is_a_secret_and_an_absent_agent_is_reported(monkeypatch):
    from agent_commercial.sources.snmp_source import SnmpSource
    with pytest.raises(ValueError, match="community_env"):
        SnmpSource({"id": "u", "host": "h", "community": "public"})
    src = SnmpSource({"id": "u", "host": "127.0.0.1", "port": _free_port(), "timeout": .3})
    src.load_points_from_config({"points": [{"point_id": "UPS-9/LOAD", "oid": "1.3.6.1.2.1.33.1.4.4.1.5.1"}]})
    assert asyncio.run(src.connect()) is False                    # no community set → refuses, never guesses "public"
    monkeypatch.setenv("C", "public")
    src = SnmpSource({"id": "u", "host": "127.0.0.1", "port": _free_port(), "timeout": .3, "community_env": "C"})
    src.load_points_from_config({"points": [{"point_id": "UPS-9/LOAD", "oid": "1.3.6.1.2.1.33.1.4.4.1.5.1"}]})
    assert asyncio.run(src.connect()) is False                    # real pysnmp, nothing listening: not connected
    assert src.get_stats()["is_connected"] is False
