"""
M-Bus (EN 13757): heat / cooling (BTU) meters, water meters, some electricity meters.

Meters hang on a two-wire M-Bus; a level converter makes it reachable over
serial or — most often on site — a TCP gateway. ARVIS asks each meter for its
current data and decodes the answer. Read-only: the only frames ARVIS ever sends
are a link reset (SND_NKE) and a data request (REQ_UD2); never SND_UD, which
would send data to a meter (asserted at the one place frames leave, and by test).

    sources:
      - id: btu
        kind: mbus
        transport: tcp                  # or serial (needs pyserial): serial_port: COM4, baudrate: 2400
        host: 10.10.0.80
        port: 10001
        poll_interval: 900
        meters:
          - {address: 1, equipment_id: MTR-BTU-T1, type: cooling}     # cooling | heat | water | electricity | gas
          - {address: 2, equipment_id: MTR-W-01, type: water}

Each meter's current values become points <equipment_id>/<NAME>: ENERGY (kWh),
VOLUME (m³), POWER (kW), FLOW (m³/h), FLOW_TEMP, RETURN_TEMP, TEMP_DIFF, EXT_TEMP
(°C/K), OP_HOURS (h), VOLTAGE (V), CURRENT (A), and STATUS_ERR (the meter reports
an error). Historic, tariff and min/max records are not points. A record this
decoder doesn't understand is skipped, never guessed.

Primary addresses (1–250) only: secondary addressing selects a meter with an
SND_UD frame, which this source does not send.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
from agent_commercial.sources.base import source_tag

logger = logging.getLogger("arvis.sources.mbus")

SND_NKE, REQ_UD2, REQ_UD2_FCB = 0x40, 0x5B, 0x7B
ALLOWED_C = (SND_NKE, REQ_UD2, REQ_UD2_FCB)          # link reset, data request. Nothing that carries data to a meter.
ACK = 0xE5
METER_TYPES = ("cooling", "heat", "water", "electricity", "gas")

# Which role each value plays, per kind of meter (coverage, FDD, unit conversion).
_ROLES: Dict[str, Dict[str, str]] = {
    "cooling": {"ENERGY": "thermal-energy", "POWER": "thermal-power", "FLOW": "water-flow", "VOLUME": "water-volume",
                "FLOW_TEMP": "chw-supply-temp", "RETURN_TEMP": "chw-return-temp"},
    "heat": {"ENERGY": "thermal-energy", "POWER": "thermal-power", "FLOW": "water-flow", "VOLUME": "water-volume"},
    "water": {"VOLUME": "water-volume", "FLOW": "water-flow"},
    "electricity": {"ENERGY": "electric-energy", "POWER": "electric-power", "VOLTAGE": "supply-voltage",
                    "CURRENT": "electric-current"},
    "gas": {},
}
_UNITS = {"ENERGY": "kWh", "VOLUME": "m³", "POWER": "kW", "FLOW": "m³/h", "FLOW_TEMP": "°C", "RETURN_TEMP": "°C",
          "TEMP_DIFF": "K", "EXT_TEMP": "°C", "OP_HOURS": "h", "VOLTAGE": "V", "CURRENT": "A", "STATUS_ERR": ""}


# ── frames ──────────────────────────────────────────────────────────────────
def short_frame(c: int, address: int) -> bytes:
    return bytes([0x10, c, address, (c + address) & 0xFF, 0x16])


def parse_long_frame(frame: bytes) -> Tuple[int, int, int, bytes]:
    """68 L L 68 C A CI data CS 16 → (C, A, CI, data). Raises ValueError on a bad frame."""
    if len(frame) < 9 or frame[0] != 0x68 or frame[3] != 0x68 or frame[1] != frame[2]:
        raise ValueError("not an M-Bus long frame")
    n = frame[1]
    if len(frame) != n + 6 or frame[-1] != 0x16:
        raise ValueError("M-Bus frame length mismatch")
    body = frame[4:4 + n]
    if sum(body) & 0xFF != frame[4 + n]:
        raise ValueError("M-Bus checksum mismatch")
    return body[0], body[1], body[2], bytes(body[3:])


# ── variable data records (EN 13757-3) ──────────────────────────────────────
@dataclass
class Record:
    name: str              # ENERGY, VOLUME, ... (see _UNITS)
    value: float           # in _UNITS[name]
    storage: int = 0
    tariff: int = 0
    function: int = 0      # 0 instantaneous, 1 max, 2 min, 3 value during error


@dataclass
class Telegram:
    meter_id: str = ""
    manufacturer: str = ""
    medium: int = 0
    status: int = 0
    records: List[Record] = field(default_factory=list)
    skipped: int = 0


def _bcd(b: bytes) -> Optional[int]:
    digits, neg = [], False
    for i, byte in enumerate(reversed(b)):
        hi, lo = byte >> 4, byte & 0x0F
        if i == 0 and hi == 0xF:          # a leading F nibble marks a negative number
            neg, hi = True, 0
        if hi > 9 or lo > 9:
            return None
        digits += [hi, lo]
    v = int("".join(map(str, digits)) or "0")
    return -v if neg else v


_LEN = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 6, 7: 8, 9: 1, 10: 2, 11: 3, 12: 4, 14: 6}


def _raw(coding: int, b: bytes) -> Optional[float]:
    if coding == 5:
        f = struct.unpack("<f", b)[0]
        return f if f == f else None
    if coding in (9, 10, 11, 12, 14):
        v = _bcd(b)
        return float(v) if v is not None else None
    return float(int.from_bytes(b, "little", signed=True))


def _lvar_size(lvar: int) -> Optional[int]:
    if lvar <= 0xBF:
        return lvar                                          # text
    if lvar <= 0xEF:
        return (lvar & 0x0F)                                 # BCD (+/-) or binary, n bytes
    if lvar <= 0xF4:
        return 4 * (lvar - 0xEC)
    return {0xF5: 6, 0xF6: 8}.get(lvar)


def _vif(vif: int, ext: List[int]) -> Optional[Tuple[str, float]]:
    """(name, multiplier into _UNITS[name]) for the VIFs this decoder knows; None for the rest."""
    v = vif & 0x7F
    if vif == 0xFD and ext:                                  # extension table FD
        e = ext[0] & 0x7F
        if 0x40 <= e <= 0x4F:
            return "VOLTAGE", 10 ** ((e & 0x0F) - 9)
        if 0x50 <= e <= 0x5F:
            return "CURRENT", 10 ** ((e & 0x0F) - 12)
        return None
    if vif == 0xFB and ext:                                  # extension table FB
        e = ext[0] & 0x7F
        if e in (0x00, 0x01):
            return "ENERGY", 10 ** ((e & 1) - 1) * 1000.0      # 0.1 / 1 MWh
        if e in (0x08, 0x09):
            return "ENERGY", 10 ** ((e & 1) - 1) * 1e6 / 3600   # 0.1 / 1 GJ
        return None
    if vif in (0xFB, 0xFD, 0x7C, 0xFC, 0x7E, 0xFE, 0x7F, 0xFF):
        return None
    if ext:                                                  # combinable extensions (phase, per-unit, ...): unknown → skip
        return None
    n = v & 0x07
    if v <= 0x07:
        return "ENERGY", 10 ** (n - 3) / 1000.0              # Wh → kWh
    if v <= 0x0F:
        return "ENERGY", 10 ** n / 3.6e6                     # J → kWh
    if v <= 0x17:
        return "VOLUME", 10 ** (n - 6)                       # m³
    if 0x20 <= v <= 0x27:
        return "OP_HOURS", (1 / 3600, 1 / 60, 1.0, 24.0)[v & 0x03]
    if 0x28 <= v <= 0x2F:
        return "POWER", 10 ** (n - 3) / 1000.0               # W → kW
    if 0x30 <= v <= 0x37:
        return "POWER", 10 ** n / 3.6e6                      # J/h → kW
    if 0x38 <= v <= 0x3F:
        return "FLOW", 10 ** (n - 6)                         # m³/h
    m = v & 0x03
    if 0x58 <= v <= 0x5B:
        return "FLOW_TEMP", 10 ** (m - 3)
    if 0x5C <= v <= 0x5F:
        return "RETURN_TEMP", 10 ** (m - 3)
    if 0x60 <= v <= 0x63:
        return "TEMP_DIFF", 10 ** (m - 3)
    if 0x64 <= v <= 0x67:
        return "EXT_TEMP", 10 ** (m - 3)
    return None


def decode_records(data: bytes) -> Tuple[List[Record], int]:
    """Variable data records → (records it understood, how many it skipped)."""
    out, skipped, i = [], 0, 0
    while i < len(data):
        dif = data[i]
        i += 1
        if dif == 0x2F:                                      # idle filler
            continue
        if dif in (0x0F, 0x1F):                              # manufacturer data to the end
            break
        coding, function = dif & 0x0F, (dif >> 4) & 0x03
        storage, tariff = (dif >> 6) & 0x01, 0
        ext, j = dif & 0x80, 0
        while ext and i < len(data):
            dife = data[i]
            i += 1
            storage |= (dife & 0x0F) << (1 + 4 * j)
            tariff |= ((dife >> 4) & 0x03) << (2 * j)
            j += 1
            ext = dife & 0x80
        if i >= len(data):
            break
        vif = data[i]
        i += 1
        vifes: List[int] = []
        more = vif & 0x80
        while more and i < len(data):
            vifes.append(data[i])
            more = data[i] & 0x80
            i += 1
        if vif in (0x7C, 0xFC) and i < len(data):           # plain-text unit: length + ASCII, after the VIFEs
            i += 1 + data[i]
        if coding == 13:                                     # variable length: the LVAR byte says how long
            if i >= len(data):
                break
            lvar = data[i]
            i += 1
            size = _lvar_size(lvar)
            if size is None:
                skipped += 1
                break
            i += size
            skipped += 1
            continue
        if coding in (8, 15) or coding not in _LEN:
            skipped += 1
            break                                            # can't know where the next record starts
        size = _LEN[coding]
        raw_bytes = data[i:i + size]
        i += size
        if size == 0:
            continue
        meaning = _vif(vif, vifes)
        raw = _raw(coding, raw_bytes) if len(raw_bytes) == size else None
        if meaning is None or raw is None:
            skipped += 1
            continue
        name, mult = meaning
        out.append(Record(name=name, value=raw * mult, storage=storage, tariff=tariff, function=function))
    return out, skipped


def decode_telegram(frame: bytes) -> Telegram:
    c, _a, ci, data = parse_long_frame(frame)
    if c & 0x0F != 0x08:
        raise ValueError(f"not a data response (C=0x{c:02X})")
    t = Telegram()
    if ci == 0x72:
        if len(data) < 12:
            raise ValueError("short M-Bus header")
        ident, man = data[0:4], int.from_bytes(data[4:6], "little")
        t.meter_id = f"{_bcd(ident):08d}" if _bcd(ident) is not None else ident[::-1].hex()
        t.manufacturer = "".join(chr(((man >> s) & 0x1F) + 64) for s in (10, 5, 0))
        t.medium, t.status = data[7], data[9]
        body = data[12:]
    elif ci == 0x78:
        body = data
    else:
        raise ValueError(f"unsupported CI 0x{ci:02X}")
    t.records, t.skipped = decode_records(body)
    return t


def current_values(t: Telegram) -> Dict[str, float]:
    """The meter's present values: storage 0, tariff 0, instantaneous. Repeats get _2, _3."""
    vals: Dict[str, float] = {}
    for r in t.records:
        if r.storage or r.tariff or r.function:
            continue
        key, k = r.name, 2
        while key in vals:
            key, k = f"{r.name}_{k}", k + 1
        vals[key] = round(r.value, 6)
    vals["STATUS_ERR"] = 1.0 if t.status & 0x1A else 0.0       # application error, permanent or temporary error
    return vals


# ── the source ──────────────────────────────────────────────────────────────
def mbus_point_entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The points each declared meter is expected to give, with their roles (for coverage / alarms)."""
    out = []
    for m in cfg.get("meters") or []:
        kind = str(m.get("type", "")).lower()
        if kind not in METER_TYPES:
            raise ValueError(f"M-Bus meter {m.get('equipment_id')}: type is one of {', '.join(METER_TYPES)}")
        eq = m.get("equipment_id")
        if not eq or not isinstance(m.get("address"), int) or not 1 <= m["address"] <= 250:
            raise ValueError(f"an M-Bus meter needs equipment_id and a primary address 1–250: {m}")
        for name, role in list(_ROLES[kind].items()) + [("STATUS_ERR", "fault-status")]:
            out.append({"point_id": f"{eq}/{name}", "equipment_id": eq, "unit": _UNITS[name], "role": role})
    return out


class MBusSource:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "mbus")
        self.transport = str(cfg.get("transport", "tcp"))
        if self.transport not in ("tcp", "serial"):
            raise ValueError(f"mbus source {self.source_id}: transport is tcp or serial")
        self.host, self.port = cfg.get("host", ""), int(cfg.get("port", 10001))
        self.serial_port, self.baudrate = cfg.get("serial_port", ""), int(cfg.get("baudrate", 2400))
        if self.transport == "tcp" and not self.host:
            raise ValueError(f"mbus source {self.source_id}: needs a host (the M-Bus gateway)")
        if self.transport == "serial" and not self.serial_port:
            raise ValueError(f"mbus source {self.source_id}: needs serial_port")
        self.timeout = float(cfg.get("timeout", 3.0))
        self.meters: List[Dict[str, Any]] = []
        self._cbs: List[Callable[[BMSDataPoint], Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._interval = 900.0
        self._freshness = PointFreshness()
        self._lock = asyncio.Lock()
        self.exchange = self._exchange_tcp if self.transport == "tcp" else self._exchange_serial
        self.stats = {"reads_total": 0, "reads_failed": 0, "records_skipped": 0, "last_read": None, "meters": {}}

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        entries = mbus_point_entries(config)
        self.meters = [dict(m, type=str(m["type"]).lower()) for m in config.get("meters") or []]
        for e in entries:
            self._freshness.register(e["point_id"])
        return len(entries)

    # ── the wire ──────────────────────────────────────────────────────────
    def _send(self, c: int, address: int) -> bytes:
        """The only place a frame is built to go to the bus."""
        if c not in ALLOWED_C:
            raise PermissionError(f"M-Bus C-field 0x{c:02X} is not a read — ARVIS never sends data to a meter")
        return short_frame(c, address)

    async def _read_frame(self, reader: asyncio.StreamReader) -> bytes:
        first = await asyncio.wait_for(reader.readexactly(1), self.timeout)
        if first[0] == ACK:
            return first
        if first[0] != 0x68:
            raise ValueError(f"unexpected M-Bus start byte 0x{first[0]:02X}")
        head = await asyncio.wait_for(reader.readexactly(3), self.timeout)
        rest = await asyncio.wait_for(reader.readexactly(head[0] + 2), self.timeout)
        return first + head + rest

    async def _exchange_tcp(self, frames: List[bytes]) -> List[bytes]:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
        try:
            out = []
            for f in frames:
                writer.write(f)
                await writer.drain()
                out.append(await self._read_frame(reader))
            return out
        finally:
            writer.close()

    async def _exchange_serial(self, frames: List[bytes]) -> List[bytes]:
        try:
            import serial  # pyserial
        except ImportError as e:
            raise ConnectionError("M-Bus over serial needs pyserial (pip install pyserial) — or use a TCP gateway") from e

        def run() -> List[bytes]:
            with serial.Serial(self.serial_port, self.baudrate, parity=serial.PARITY_EVEN, timeout=self.timeout) as s:
                out = []
                for f in frames:
                    s.reset_input_buffer()
                    s.write(f)
                    first = s.read(1)
                    if not first:
                        raise TimeoutError("meter did not answer")
                    if first[0] == ACK:
                        out.append(first)
                        continue
                    head = s.read(3)
                    out.append(first + head + s.read(head[0] + 2 if head else 0))
                return out
        return await asyncio.to_thread(run)

    async def read_meter(self, address: int) -> Telegram:
        async with self._lock:                          # one conversation on the bus at a time
            ack, resp = await self.exchange([self._send(SND_NKE, address), self._send(REQ_UD2, address)])
        if ack != bytes([ACK]):
            raise ValueError(f"meter {address} did not acknowledge the link reset")
        return decode_telegram(resp)

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        if not self.meters:
            self._connected = False
            return False
        try:
            await self.read_meter(self.meters[0]["address"])
            self._connected = True
        except Exception as e:
            where = f"{self.host}:{self.port}" if self.transport == "tcp" else self.serial_port
            logger.error(f"[M-Bus] {self.source_id}: {where} meter {self.meters[0]['address']} not answering: "
                         f"{type(e).__name__}: {e}")
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

    async def start_polling(self, interval_seconds: float = 900) -> None:
        self._interval = float(interval_seconds)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop_polling(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self.read_all()
            await asyncio.sleep(self._interval)

    async def read_all(self) -> int:
        n, ok = 0, 0
        for m in self.meters:
            self.stats["reads_total"] += 1
            try:
                t = await self.read_meter(m["address"])
            except Exception as e:
                self.stats["reads_failed"] += 1
                logger.warning(f"[M-Bus] {self.source_id}: meter {m['address']} ({m['equipment_id']}): "
                               f"{type(e).__name__}: {e}")
                continue
            ok += 1
            self.stats["records_skipped"] += t.skipped
            self.stats["meters"][m["equipment_id"]] = {"id": t.meter_id, "manufacturer": t.manufacturer,
                                                      "medium": t.medium, "status": t.status}
            now = datetime.now()
            for name, value in current_values(t).items():
                pid = f"{m['equipment_id']}/{name}"
                pt = BMSDataPoint(point_id=pid, name=pid, value=value, unit=_UNITS[re.sub(r"_\d+$", "", name)],
                                  timestamp=now, source=source_tag("mbus", self.source_id), equipment_id=m["equipment_id"],
                                  point_type=PointType.SENSOR,
                                  quality=PointQuality.UNCERTAIN if t.status & 0x1A and name != "STATUS_ERR" else PointQuality.GOOD)
                self._freshness.mark_ok(pid)
                for cb in self._cbs:
                    out = cb(pt)
                    if inspect.isawaitable(out):
                        await out
                n += 1
        self._connected = ok > 0
        for pid in self._freshness.newly_stale({e["point_id"]: self._interval for e in mbus_point_entries(
                {"meters": self.meters})}):
            logger.info(f"[M-Bus] {self.source_id}: {pid} has not been read for a while (stale)")
        self.stats["last_read"] = datetime.now().isoformat(timespec="seconds")
        return n

    def get_stats(self) -> Dict[str, Any]:
        where = f"{self.host}:{self.port}" if self.transport == "tcp" else self.serial_port
        return {**self.stats, "is_connected": self._connected, "polling_active": bool(self._task and not self._task.done()),
                "meters_configured": len(self.meters), "stale_points": self._freshness.stale_points, "gateway": where}


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("mbus", build=MBusSource, points_config=lambda cfg: cfg, point_entries=mbus_point_entries,
                    default_poll=900.0)
