"""
MQTT: modern IoT and retrofit sensors, and LoRaWAN through its network server.

Current clamps on pumps, vibration sensors on motors, pipe and cold-room
temperature, leak sensors, air quality, tank levels — most retrofit sensors (and
every LoRaWAN network server) publish over MQTT. ARVIS subscribes; it never
publishes (read-only, enforced by test).

    sources:
      - id: iot
        kind: mqtt
        host: 127.0.0.1            # the bundled local broker (docker-compose.site.yml), or the site's own
        port: 1883
        username_env: ARVIS_MQTT_USERNAME
        password_env: ARVIS_MQTT_PASSWORD
        stale_after_s: 900          # a sensor silent this long goes STALE (default 3600)
        points:
          - {point_id: CHWP-1/AMPS, topic: plant/chwp1/current, value: "$.amps", unit: A, equipment_id: CHWP-1}
          - {point_id: COLD-1/TEMP, topic: kitchen/coldroom1, value: "$.temperature", ts: "$.time", unit: "°C"}
          # LoRaWAN: name the device and the decoded field, the preset knows the topic and payload shape
          - {point_id: TANK-1/LVL, preset: chirpstack, device: a84041000181c45b, field: level, unit: "%"}
          - {point_id: LEAK-B2/WET, preset: ttn, device: leak-b2-01, field: water_leak}

value is a JSON path into the payload ('$.a.b', '$.list[0]'); without one the
whole payload is the value (plain numbers, "on"/"off"). ts, when given, is the
reading's own time; otherwise the time it arrived. scale / offset as for Modbus.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
from agent_commercial.sources.base import source_tag
from agent_commercial.sources.common import json_path, number, refuse_inline_secrets, secret, timestamp

logger = logging.getLogger("arvis.sources.mqtt")

# LoRaWAN network servers: where a device's decoded uplink appears, and how it is shaped.
PRESETS = {
    "chirpstack": {"topic": "application/+/device/{device}/event/up", "value": "$.object.{field}", "ts": "$.time"},
    "ttn": {"topic": "v3/+/devices/{device}/up", "value": "$.uplink_message.decoded_payload.{field}",
            "ts": "$.received_at"},
}


@dataclass
class MqttPoint:
    point_id: str
    topic: str
    value: Optional[str] = None
    ts: Optional[str] = None
    unit: str = ""
    name: str = ""
    equipment_id: str = ""
    scale: float = 1.0
    offset: float = 0.0


def topic_matches(filt: str, topic: str) -> bool:
    """MQTT wildcard match: '+' one level, '#' the rest."""
    f, t = filt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


def point_from_config(e: Dict[str, Any]) -> MqttPoint:
    if not e.get("point_id"):
        raise ValueError("an MQTT point needs a point_id")
    e = dict(e)
    if e.get("preset"):
        pre = PRESETS.get(e["preset"])
        if pre is None:
            raise ValueError(f"{e['point_id']}: unknown preset {e['preset']!r} (known: {', '.join(PRESETS)})")
        if not e.get("device") or not e.get("field"):
            raise ValueError(f"{e['point_id']}: a {e['preset']} point needs device and field")
        e.setdefault("topic", pre["topic"].format(device=e["device"]))
        e.setdefault("value", pre["value"].format(field=e["field"]))
        e.setdefault("ts", pre["ts"])
    if not e.get("topic"):
        raise ValueError(f"{e['point_id']}: an MQTT point needs a topic (or a preset)")
    return MqttPoint(point_id=e["point_id"], topic=e["topic"], value=e.get("value"), ts=e.get("ts"),
                     unit=e.get("unit", ""), name=e.get("name") or e["point_id"],
                     equipment_id=e.get("equipment_id") or e["point_id"].split("/")[0],
                     scale=float(e.get("scale", 1.0)), offset=float(e.get("offset", 0.0)))


class MqttSource:
    def __init__(self, cfg: Dict[str, Any]):
        refuse_inline_secrets(cfg, f"mqtt source {cfg.get('id', '')}")
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "mqtt")
        self.host = cfg.get("host", "127.0.0.1")
        self.port = int(cfg.get("port", 1883))
        self.username = secret(cfg, "username") or cfg.get("username")
        self.password = secret(cfg, "password")
        self.tls = bool(cfg.get("tls", False))
        self.stale_after_s = float(cfg.get("stale_after_s", 3600))
        self.points: List[MqttPoint] = []
        self._cbs: List[Callable[[BMSDataPoint], Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._stale_task: Optional[asyncio.Task] = None
        self._connected = False
        self._last: Dict[str, BMSDataPoint] = {}
        self._freshness = PointFreshness(stale_factor=1.0)
        self.client_factory = None             # tests: a scripted client; default aiomqtt.Client
        self.stats = {"messages": 0, "readings": 0, "unparsed": 0, "reconnects": 0, "last_message": None}

    # ── config ────────────────────────────────────────────────────────────
    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        self.points = [point_from_config(e) for e in (config.get("points") or []) if isinstance(e, dict)]
        for p in self.points:
            self._freshness.register(p.point_id)
        return len(self.points)

    def filters(self) -> List[str]:
        return sorted({p.topic for p in self.points})

    # ── connection ────────────────────────────────────────────────────────
    def _client(self):
        if self.client_factory is not None:
            return self.client_factory(self)
        import aiomqtt
        tls = None
        if self.tls:
            import ssl
            tls = aiomqtt.TLSParameters(cert_reqs=ssl.CERT_REQUIRED)
        return aiomqtt.Client(hostname=self.host, port=self.port, username=self.username, password=self.password,
                              identifier=f"arvis-{self.source_id}", tls_params=tls, timeout=10)

    async def connect(self) -> bool:
        """One check that the broker is reachable; the listener (start_polling) keeps the session."""
        try:
            async with self._client():
                pass
            self._connected = True
        except Exception as e:
            logger.error(f"[MQTT] {self.source_id}: cannot reach {self.host}:{self.port}: {type(e).__name__}: {e}")
            self._connected = False
        return self._connected

    async def disconnect(self) -> None:
        await self.stop_polling()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def on_point_update(self, cb: Callable[[BMSDataPoint], Any]) -> None:
        self._cbs.append(cb)

    async def start_polling(self, interval_seconds: float = 30) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._listen())
        if self._stale_task is None or self._stale_task.done():
            self._stale_task = asyncio.create_task(self._watch_stale(max(5.0, min(60.0, self.stale_after_s / 3))))

    async def stop_polling(self) -> None:
        for t in (self._task, self._stale_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = self._stale_task = None

    async def _listen(self) -> None:
        delay = 2.0
        while True:
            try:
                async with self._client() as client:
                    for f in self.filters():
                        await client.subscribe(f)
                    self._connected, delay = True, 2.0
                    logger.info(f"[MQTT] {self.source_id}: subscribed to {len(self.filters())} topics on {self.host}")
                    async for msg in client.messages:
                        await self.handle(str(msg.topic), msg.payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._connected = False
                self.stats["reconnects"] += 1
                logger.warning(f"[MQTT] {self.source_id}: connection lost ({type(e).__name__}: {e}); retry in {delay:g}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300.0)

    # ── messages ──────────────────────────────────────────────────────────
    async def handle(self, topic: str, payload: Any) -> int:
        """One message → the readings it carries. Returns how many points it updated."""
        self.stats["messages"] += 1
        self.stats["last_message"] = datetime.now().isoformat(timespec="seconds")
        raw = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        try:
            doc: Any = json.loads(raw)
        except ValueError:
            doc = raw
        n = 0
        for p in self.points:
            if not topic_matches(p.topic, topic):
                continue
            v = number(json_path(doc, p.value)) if p.value else number(doc)
            if v is None:
                self.stats["unparsed"] += 1
                continue
            ts = timestamp(json_path(doc, p.ts)) if p.ts and isinstance(doc, (dict, list)) else None
            pt = BMSDataPoint(point_id=p.point_id, name=p.name, value=v * p.scale + p.offset, unit=p.unit,
                              timestamp=ts or datetime.now(), source=source_tag("mqtt", self.source_id),
                              equipment_id=p.equipment_id, point_type=PointType.SENSOR, quality=PointQuality.GOOD)
            self._freshness.mark_ok(p.point_id)
            self._last[p.point_id] = pt
            await self._emit(pt)
            n += 1
        self.stats["readings"] += n
        return n

    async def _emit(self, pt: BMSDataPoint) -> None:
        for cb in self._cbs:
            out = cb(pt)
            if inspect.isawaitable(out):
                await out

    async def _watch_stale(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            for pid in self._freshness.newly_stale({p.point_id: self.stale_after_s for p in self.points}):
                last = self._last.get(pid)
                if last is not None:      # the last value, marked STALE once — never a made-up one
                    await self._emit(BMSDataPoint(point_id=pid, name=last.name, value=last.value, unit=last.unit,
                                                  timestamp=last.timestamp, source=last.source,
                                                  equipment_id=last.equipment_id, quality=PointQuality.STALE))

    def get_stats(self) -> Dict[str, Any]:
        return {**self.stats, "is_connected": self._connected, "polling_active": bool(self._task and not self._task.done()),
                "points_configured": len(self.points), "stale_points": self._freshness.stale_points,
                "broker": f"{self.host}:{self.port}"}


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("mqtt", build=MqttSource, points_config=lambda cfg: cfg,
                    point_entries=lambda cfg: list(cfg.get("points") or []))
