"""
ArvisX live MQTT validation — real broker + real paho client end to end.

Closes the #1 untested gap: until now MQTT was exercised only via the pure handler
(no broker). Here an in-process amqtt broker runs on 127.0.0.1:1883; the real paho
MqttIngest subscribes; a real paho publisher emits a scenario; we assert the signals
flowed broker → ingest → AssetStore → report.

Run: python scratch/arvisx_mqtt_live.py
"""
import asyncio
import threading
import time

import paho.mqtt.client as mqtt

from arvisx.store import AssetStore
from arvisx.ingest.mqtt_adapter import MqttIngest
from arvisx.ingest.mock_publisher import scenario_messages
from arvisx.simulator import healthy_community
from arvisx.health import build_report

BROKER, PORT = "127.0.0.1", 1883


def start_broker():
    """Run an amqtt broker in a dedicated thread/loop."""
    from amqtt.broker import Broker
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"{BROKER}:{PORT}"}},
           "auth": {"allow-anonymous": True}}

    async def _run():
        broker = Broker(cfg)            # construct inside the running loop
        await broker.start()
        while True:
            await asyncio.sleep(3600)
    loop.run_until_complete(_run())


def main():
    threading.Thread(target=start_broker, daemon=True).start()
    time.sleep(2.5)   # let the broker bind

    # Real paho ingest against the real broker.
    store = AssetStore.from_fleet_definition(healthy_community())
    ingest = MqttIngest(store, broker=BROKER, port=PORT)
    ingest.start(loop=False)
    time.sleep(1.0)

    before = len(build_report(store.snapshot()).risks)

    # Real paho publisher → broker.
    pub = mqtt.Client(client_id="arvisx-live-pub")
    pub.connect(BROKER, PORT, 30)
    pub.loop_start()
    msgs = scenario_messages("prd")
    for topic, payload in msgs:
        pub.publish(topic, payload, qos=1)
    time.sleep(2.5)   # let messages traverse broker → ingest
    pub.loop_stop(); pub.disconnect()

    rep = build_report(store.snapshot())
    telemetry = [r for r in rep.risks if any(k in r.message.lower()
                 for k in ("runtime above", "below normal", "test overdue"))]
    print(f"published      : {len(msgs)} messages (real paho → real broker)")
    print(f"ingest received: {ingest.received} | accepted: {ingest.accepted}")
    print(f"store updates  : {store.update_count}")
    print(f"risks before/after ingest: {before} / {len(rep.risks)}")
    print(f"telemetry-driven risks surfaced live: {[r.message for r in telemetry]}")
    ingest.stop()
    ok = ingest.received > 0 and store.update_count > 0 and len(telemetry) >= 2
    print("\nRESULT:", "PASS — real broker ↔ real paho ↔ ArvisX intelligence verified" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
