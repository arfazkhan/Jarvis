"""
MQTT ingest adapter — thin paho shell around the pure parse/handle logic.

Subscribes to <prefix>/# on a broker and applies every message to an AssetStore.
The handler (`handle_message`) is pure and tested without a broker; only `start()`
touches the network. paho-mqtt import is guarded so the package imports even where
paho isn't installed (matches the commercial modbus adapter's pattern).

Run a broker for real use, e.g.:
    docker run -it -p 1883:1883 eclipse-mosquitto
    # or install mosquitto locally
"""
from __future__ import annotations

import logging
from typing import List

from arvisx.ingest.topics import Reading, parse
from arvisx.store import AssetStore

logger = logging.getLogger("arvisx.ingest.mqtt")

try:
    import paho.mqtt.client as mqtt  # type: ignore
    _PAHO = True
except ImportError:  # pragma: no cover
    mqtt = None
    _PAHO = False


def handle_message(store: AssetStore, topic: str, payload: str, prefix: str = "arvisx") -> List[Reading]:
    """Pure: parse one message → apply readings to the store. Returns the readings
    that were ACCEPTED (asset known). Unknown assets / malformed messages → []."""
    accepted: List[Reading] = []
    for (asset_id, key, value) in parse(topic, payload, prefix):
        if store.apply_reading(asset_id, key, value):
            accepted.append((asset_id, key, value))
        else:
            logger.debug(f"[MQTT] dropped reading for unknown asset '{asset_id}' (topic={topic})")
    return accepted


class MqttIngest:
    def __init__(self, store: AssetStore, broker: str = "localhost", port: int = 1883,
                 prefix: str = "arvisx", client_id: str = "arvisx-ingest"):
        if not _PAHO:
            raise RuntimeError("paho-mqtt not installed — pip install paho-mqtt")
        self.store = store
        self.broker = broker
        self.port = port
        self.prefix = prefix
        self.received = 0
        self.accepted = 0
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        sub = f"{self.prefix}/#"
        client.subscribe(sub)
        logger.info(f"[MQTT] connected rc={rc}, subscribed {sub}")

    def _on_message(self, client, userdata, msg):
        self.received += 1
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        self.accepted += len(handle_message(self.store, msg.topic, payload, self.prefix))

    def start(self, loop: bool = True):
        """Connect + start the network loop (blocking if loop=True, else background)."""
        self._client.connect(self.broker, self.port, keepalive=60)
        if loop:
            self._client.loop_forever()
        else:
            self._client.loop_start()

    def stop(self):
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
