"""
KNX (listen-only): lighting, blinds, room controllers — and DALI lighting through
a KNX-DALI gateway.

KNX devices announce their state on the bus as group telegrams. ARVIS listens
through the installation's KNX IP router or IP interface and never puts a telegram
on the bus:

  routing      the IP router's multicast (224.0.23.12:3671). ARVIS only receives —
               it sends nothing at all.
  tunnelling   an IP interface. ARVIS opens a tunnel and keeps it alive; the only
               frames it sends are the tunnel's own connect / heartbeat / ack /
               disconnect. Never a TUNNELLING_REQUEST, the frame that carries a
               telegram onto the bus (asserted at the one place frames leave, and by test).

    sources:
      - id: knx
        kind: knx
        mode: routing                       # or tunnelling: host: 10.10.0.90 (port 3671)
        points:
          - {point_id: LGT-L5/LEVEL, ga: 1/2/3, dpt: "5.001", role: light-level}
          - {point_id: RM-501/TEMP, ga: 3/1/10, dpt: "9.001", role: zone-temp, max_silence_s: 3600}
        devices:                            # templates: config/templates/knx/*.yaml
          - {template: dali_light, equipment_id: LGT-L5-01, ga: {STATUS: 1/4/3, LEVEL: 1/2/3, FAULT: 1/7/3}}

A value arrives when a device sends it (on change, or cyclically if the device is
set up to). Listening never asks, so a point shows nothing until its first
telegram. max_silence_s marks a point stale if a device that sends cyclically
goes quiet. KNX Secure (encrypted) installations are not supported.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import socket
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
from agent_commercial.sources.base import source_tag

logger = logging.getLogger("arvis.sources.knx")
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "templates" / "knx"

# KNXnet/IP service types
CONNECT_REQUEST, CONNECT_RESPONSE = 0x0205, 0x0206
CONNECTIONSTATE_REQUEST, CONNECTIONSTATE_RESPONSE = 0x0207, 0x0208
DISCONNECT_REQUEST, DISCONNECT_RESPONSE = 0x0209, 0x020A
TUNNELLING_REQUEST, TUNNELLING_ACK = 0x0420, 0x0421
ROUTING_INDICATION = 0x0530
# What ARVIS may send: keeping a tunnel open, nothing that reaches the bus.
ALLOWED_TO_SEND = (CONNECT_REQUEST, CONNECTIONSTATE_REQUEST, DISCONNECT_REQUEST, DISCONNECT_RESPONSE, TUNNELLING_ACK)
L_DATA_IND = 0x29
GROUP_READ, GROUP_RESPONSE, GROUP_WRITE = 0, 1, 2


# ── group addresses and datapoint types ─────────────────────────────────────
def parse_ga(ga: Any) -> int:
    """'1/2/3' (3-level), '1/515' (2-level) or a raw int → the 16-bit group address."""
    if isinstance(ga, int):
        return ga
    parts = [int(x) for x in str(ga).strip().split("/")]
    if len(parts) == 3 and parts[0] <= 31 and parts[1] <= 7 and parts[2] <= 255:
        return (parts[0] << 11) | (parts[1] << 8) | parts[2]
    if len(parts) == 2 and parts[0] <= 31 and parts[1] <= 2047:
        return (parts[0] << 11) | parts[1]
    raise ValueError(f"not a KNX group address: {ga!r}")


def format_ga(a: int) -> str:
    return f"{(a >> 11) & 0x1F}/{(a >> 8) & 0x07}/{a & 0xFF}"


def _float16(b: bytes) -> Optional[float]:
    raw = (b[0] << 8) | b[1]
    if raw == 0x7FFF:                                  # "invalid data"
        return None
    mant = raw & 0x07FF
    if raw & 0x8000:
        mant -= 2048
    return round(0.01 * mant * (1 << ((raw >> 11) & 0x0F)), 2)


def decode_dpt(dpt: str, small: int, data: bytes) -> Optional[float]:
    """A telegram's value for the datapoint types building systems use. None if it doesn't fit."""
    main, _, sub = str(dpt).partition(".")
    try:
        if main == "1":
            return float(small & 0x01)
        if main == "5":
            if len(data) != 1:
                return None
            return round(data[0] * 100 / 255, 1) if sub in ("001", "1") else float(data[0])
        if main == "6" and len(data) == 1:
            return float(struct.unpack(">b", data)[0])
        if main == "7" and len(data) == 2:
            return float(struct.unpack(">H", data)[0])
        if main == "8" and len(data) == 2:
            return float(struct.unpack(">h", data)[0])
        if main == "9" and len(data) == 2:
            return _float16(data)
        if main == "12" and len(data) == 4:
            return float(struct.unpack(">I", data)[0])
        if main == "13" and len(data) == 4:
            return float(struct.unpack(">i", data)[0])
        if main == "14" and len(data) == 4:
            f = struct.unpack(">f", data)[0]
            return f if f == f else None
    except struct.error:
        return None
    return None


SUPPORTED_DPT_MAINS = ("1", "5", "6", "7", "8", "9", "12", "13", "14")


@dataclass
class GroupTelegram:
    source: str
    ga: int
    apci: int
    small: int                 # the 6-bit value carried in the APCI byte (DPT 1/2/3)
    data: bytes


def parse_cemi(cemi: bytes) -> Optional[GroupTelegram]:
    """A cEMI L_Data.ind carrying a group value write/response → GroupTelegram; anything else → None."""
    if len(cemi) < 2 or cemi[0] != L_DATA_IND:
        return None
    i = 2 + cemi[1]
    if len(cemi) < i + 8:
        return None
    ctrl2 = cemi[i + 1]
    if not ctrl2 & 0x80:                               # individual (device) address: not a group value
        return None
    src = int.from_bytes(cemi[i + 2:i + 4], "big")
    dst = int.from_bytes(cemi[i + 4:i + 6], "big")
    npdu_len, tpci, apci_lo = cemi[i + 6], cemi[i + 7], cemi[i + 8]
    apci = ((tpci & 0x03) << 2) | (apci_lo >> 6)
    if apci not in (GROUP_RESPONSE, GROUP_WRITE):
        return None
    data = bytes(cemi[i + 9:i + 9 + max(0, npdu_len - 1)]) if npdu_len > 1 else b""
    return GroupTelegram(source=f"{(src >> 12) & 0xF}.{(src >> 8) & 0xF}.{src & 0xFF}", ga=dst, apci=apci,
                         small=apci_lo & 0x3F, data=data)


def _header(service: int, body_len: int) -> bytes:
    return struct.pack(">BBHH", 0x06, 0x10, service, 6 + body_len)


def _hpai(ip: str = "0.0.0.0", port: int = 0) -> bytes:
    return struct.pack(">BB4sH", 8, 1, socket.inet_aton(ip), port)


# ── templates (a KNX-DALI gateway's objects, a room controller, ...) ────────
def expand_devices(devices: List[Dict[str, Any]], directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    import yaml
    out = []
    for d in devices or []:
        path = (directory or TEMPLATE_DIR) / f"{d.get('template')}.yaml"
        if not path.exists():
            known = sorted(p.stem for p in (directory or TEMPLATE_DIR).glob("*.yaml"))
            raise ValueError(f"unknown KNX template {d.get('template')!r} (known: {', '.join(known)})")
        eq, gas = d.get("equipment_id"), d.get("ga") or {}
        if not eq:
            raise ValueError(f"KNX device {d.get('template')}: needs an equipment_id")
        t = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = {o["suffix"] for o in t.get("objects") or []}
        unknown = set(gas) - names
        if unknown:
            raise ValueError(f"KNX device {eq}: {', '.join(sorted(unknown))} not in template {d['template']} "
                             f"({', '.join(sorted(names))})")
        for o in t.get("objects") or []:
            if o["suffix"] not in gas:
                continue                               # this installation doesn't expose that object
            e = {k: v for k, v in o.items() if k != "suffix"}
            e.update(point_id=f"{eq}/{o['suffix']}", equipment_id=eq, ga=gas[o["suffix"]])
            out.append(e)
    return out


def knx_point_entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(cfg.get("points") or []) + expand_devices(cfg.get("devices") or [])


@dataclass
class KnxPoint:
    point_id: str
    ga: int
    dpt: str
    unit: str = ""
    equipment_id: str = ""
    max_silence_s: Optional[float] = None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "KnxSource"):
        self.owner = owner

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        self.owner._received(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning(f"[KNX] {self.owner.source_id}: socket error: {exc}")


class KnxSource:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "knx")
        self.mode = str(cfg.get("mode", "routing"))
        if self.mode not in ("routing", "tunnelling"):
            raise ValueError(f"knx source {self.source_id}: mode is routing or tunnelling")
        self.host, self.port = cfg.get("host", ""), int(cfg.get("port", 3671))
        if self.mode == "tunnelling" and not self.host:
            raise ValueError(f"knx source {self.source_id}: tunnelling needs the IP interface's host")
        self.multicast_group = cfg.get("multicast_group", "224.0.23.12")
        self.local_ip = cfg.get("local_ip", "0.0.0.0")
        self.timeout = float(cfg.get("timeout", 5.0))
        self.heartbeat_s = float(cfg.get("heartbeat_s", 60.0))
        self.points: Dict[int, List[KnxPoint]] = {}
        self._cbs: List[Callable[[BMSDataPoint], Any]] = []
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._connected = False
        self._channel: Optional[int] = None
        self._last_seq: Optional[int] = None
        self._waiters: Dict[int, asyncio.Future] = {}
        self._task: Optional[asyncio.Task] = None
        self._pending: set = set()
        self._freshness = PointFreshness(stale_factor=1.0)    # max_silence_s is the limit itself
        self._last: Dict[str, BMSDataPoint] = {}
        self.sent: List[int] = []                     # service types sent (stats; tests)
        self.stats = {"telegrams": 0, "ignored_unmapped": 0, "undecodable": 0, "reconnects": 0, "last_telegram": None}

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        self.points = {}
        n = 0
        for e in knx_point_entries(config):
            if not e.get("point_id") or e.get("ga") is None or not e.get("dpt"):
                raise ValueError(f"a KNX point needs point_id, ga and dpt: {e}")
            dpt = str(e["dpt"])
            if dpt.partition(".")[0] not in SUPPORTED_DPT_MAINS:
                raise ValueError(f"KNX point {e['point_id']}: DPT {dpt} not supported "
                                 f"(supported: {', '.join(SUPPORTED_DPT_MAINS)})")
            p = KnxPoint(point_id=e["point_id"], ga=parse_ga(e["ga"]), dpt=dpt, unit=e.get("unit", ""),
                         equipment_id=e.get("equipment_id") or e["point_id"].split("/")[0],
                         max_silence_s=float(e["max_silence_s"]) if e.get("max_silence_s") else None)
            self.points.setdefault(p.ga, []).append(p)
            self._freshness.register(p.point_id)
            n += 1
        return n

    # ── the wire ──────────────────────────────────────────────────────────
    def _send(self, service: int, body: bytes) -> None:
        """The only place a frame leaves ARVIS."""
        if service not in ALLOWED_TO_SEND:
            raise PermissionError(f"KNXnet/IP service 0x{service:04X} would reach the bus — ARVIS only listens")
        if self.mode == "routing":
            raise PermissionError("routing mode is receive-only")
        assert self._transport is not None
        self._transport.sendto(_header(service, len(body)) + body, (self.host, self.port))
        self.sent.append(service)

    def _received(self, data: bytes, addr: Tuple[str, int]) -> None:
        if len(data) < 6 or data[0] != 0x06 or data[1] != 0x10:
            return
        service = (data[2] << 8) | data[3]
        body = data[6:]
        if service == ROUTING_INDICATION and self.mode == "routing":
            self._telegram(body)
        elif service == TUNNELLING_REQUEST and self.mode == "tunnelling" and len(body) >= 4:
            channel, seq = body[1], body[2]
            if channel != self._channel:
                return
            self._send(TUNNELLING_ACK, bytes([4, channel, seq, 0]))      # every request is acked, repeats too
            if seq == self._last_seq:
                return                                                   # a repeat: already handled
            self._last_seq = seq
            self._telegram(body[body[0]:])
        elif service == DISCONNECT_REQUEST and self.mode == "tunnelling" and body[:1] == bytes([self._channel or 0]):
            self._send(DISCONNECT_RESPONSE, bytes([self._channel or 0, 0]))
            self._connected, self._channel = False, None
            logger.warning(f"[KNX] {self.source_id}: the interface closed the tunnel — reconnecting")
        elif service in (CONNECT_RESPONSE, CONNECTIONSTATE_RESPONSE, DISCONNECT_RESPONSE):
            fut = self._waiters.pop(service, None)
            if fut is not None and not fut.done():
                fut.set_result(body)

    def _telegram(self, cemi: bytes) -> None:
        t = parse_cemi(cemi)
        if t is None:
            return
        self.stats["telegrams"] += 1
        self.stats["last_telegram"] = datetime.now().isoformat(timespec="seconds")
        pts = self.points.get(t.ga)
        if not pts:
            self.stats["ignored_unmapped"] += 1
            return
        for p in pts:
            v = decode_dpt(p.dpt, t.small, t.data)
            if v is None:
                self.stats["undecodable"] += 1
                logger.info(f"[KNX] {self.source_id}: {format_ga(t.ga)} ({p.point_id}) sent data that doesn't fit DPT {p.dpt}")
                continue
            pt = BMSDataPoint(point_id=p.point_id, name=p.point_id, value=v, unit=p.unit, timestamp=datetime.now(),
                              source=source_tag("knx", self.source_id), equipment_id=p.equipment_id,
                              point_type=PointType.SENSOR, quality=PointQuality.GOOD)
            self._freshness.mark_ok(p.point_id)
            self._last[p.point_id] = pt
            self._dispatch(pt)

    def _dispatch(self, pt: BMSDataPoint) -> None:
        for cb in self._cbs:
            out = cb(pt)
            if inspect.isawaitable(out):
                task = asyncio.ensure_future(out)
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)

    async def _request(self, service: int, body: bytes, answer: int) -> bytes:
        fut = asyncio.get_running_loop().create_future()
        self._waiters[answer] = fut
        self._send(service, body)
        try:
            return await asyncio.wait_for(fut, self.timeout)
        finally:
            self._waiters.pop(answer, None)

    async def _open_tunnel(self) -> bool:
        cri = bytes([4, 0x04, 0x02, 0])                # tunnel connection, link layer
        body = await self._request(CONNECT_REQUEST, _hpai(self.local_ip) + _hpai(self.local_ip) + cri, CONNECT_RESPONSE)
        if len(body) < 2 or body[1] != 0:
            logger.error(f"[KNX] {self.source_id}: interface refused the tunnel (status 0x{body[1] if len(body) > 1 else 0xFF:02X}"
                         " — all its tunnels may be in use)")
            return False
        self._channel, self._last_seq = body[0], None
        return True

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            if self._transport is None:
                if self.mode == "routing":
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("", self.port))
                    if self.multicast_group:
                        mreq = socket.inet_aton(self.multicast_group) + socket.inet_aton(self.local_ip)
                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self), sock=sock)
                else:
                    self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self),
                                                                             local_addr=(self.local_ip, 0))
            self._connected = True if self.mode == "routing" else await self._open_tunnel()
        except Exception as e:
            where = f"{self.multicast_group}:{self.port}" if self.mode == "routing" else f"{self.host}:{self.port}"
            logger.error(f"[KNX] {self.source_id}: can't listen on {where}: {type(e).__name__}: {e}")
            self._connected = False
        return self._connected

    async def disconnect(self) -> None:
        await self.stop_polling()
        if self.mode == "tunnelling" and self._channel is not None and self._transport is not None:
            try:
                await self._request(DISCONNECT_REQUEST, bytes([self._channel, 0]) + _hpai(self.local_ip), DISCONNECT_RESPONSE)
            except Exception:
                pass
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._connected, self._channel = False, None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def on_point_update(self, cb: Callable[[BMSDataPoint], Any]) -> None:
        self._cbs.append(cb)

    async def start_polling(self, interval_seconds: float = 60) -> None:
        """Nothing is polled: telegrams arrive by themselves. This keeps a tunnel alive
        (heartbeat, reconnect) and checks for devices that have gone quiet."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._keepalive())

    async def stop_polling(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _keepalive(self) -> None:
        misses = 0
        while True:
            await asyncio.sleep(self.heartbeat_s)
            await self.check()
            if self.mode != "tunnelling":
                continue
            if self._channel is None:
                self.stats["reconnects"] += 1
                self._connected = await self.connect()
                continue
            try:
                body = await self._request(CONNECTIONSTATE_REQUEST, bytes([self._channel, 0]) + _hpai(self.local_ip),
                                           CONNECTIONSTATE_RESPONSE)
                misses = 0 if len(body) > 1 and body[1] == 0 else misses + 1
            except asyncio.TimeoutError:
                misses += 1
            if misses >= 3:
                logger.warning(f"[KNX] {self.source_id}: tunnel heartbeat lost — reconnecting")
                self._connected, self._channel, misses = False, None, 0

    async def check(self) -> List[str]:
        """Points whose device has been silent longer than its max_silence_s."""
        limits = {p.point_id: p.max_silence_s for ps in self.points.values() for p in ps if p.max_silence_s}
        stale = self._freshness.newly_stale(limits)
        for pid in stale:
            logger.info(f"[KNX] {self.source_id}: {pid} silent for over {limits[pid]:.0f}s (stale)")
            last = self._last.get(pid)
            if last is not None:
                self._dispatch(BMSDataPoint(point_id=pid, name=last.name, value=last.value, unit=last.unit,
                                            timestamp=last.timestamp, source=last.source,
                                            equipment_id=last.equipment_id, quality=PointQuality.STALE))
        return stale

    def get_stats(self) -> Dict[str, Any]:
        return {**self.stats, "is_connected": self._connected, "mode": self.mode,
                "polling_active": bool(self._task and not self._task.done()),
                "points_configured": sum(len(v) for v in self.points.values()),
                "stale_points": self._freshness.stale_points, "tunnel_channel": self._channel}


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("knx", build=KnxSource, points_config=lambda cfg: cfg, point_entries=knx_point_entries,
                    default_poll=60.0)
