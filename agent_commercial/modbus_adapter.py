"""
Modbus TCP/RTU Adapter — read-only
===================================

Async-native Modbus adapter for ARVIS BMS integration.
Mirrors the BACnetAdapter interface pattern.

Supports:
- Modbus TCP (port 502)
- Modbus RTU over TCP (serial-over-IP)
- Holding Registers (FC03), Input Registers (FC04), Coils (FC01) — read only

Register mapping config:
    {
        "host": "192.168.1.100",
        "port": 502,
        "unit_id": 1,
        "registers": [
            {
                "register_type": "holding",   # holding | input | coil
                "address": 100,
                "point_id": "AHU-03/SAT",
                "point_name": "Supply Air Temp",
                "equipment_id": "AHU-03",
                "unit": "°C",
                "scale": 0.1,    # value * scale = engineering unit
                "offset": 0.0,
                "data_type": "uint16",   # uint16 | int16 | uint32 | int32 | float32
                "word_order": "big",     # 32-bit: which register holds the high word
                "byte_order": "big",     # byte order inside each 16-bit register
                "poll_interval": 60,     # optional per-point interval (s)
            }
        ]
    }

Meters and VFDs commonly publish 32-bit floats across two registers with
vendor-specific word order ("CDAB" = word_order little); get it wrong and the
reading is garbage, so it is explicit per point.
"""

import asyncio
import inspect
import logging
import math
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
import warnings

try:
    from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    warnings.warn("pymodbus not installed. Run: pip install pymodbus")

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import (
    BMSDataPoint,
    PointType,
    PointQuality,
)

logger = logging.getLogger("arvis.bms.modbus")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

_REGISTER_COUNT = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}
_STRUCT = {"uint32": ">I", "int32": ">i", "float32": ">f"}


@dataclass
class ModbusPoint:
    """Configuration for a single Modbus register point."""
    register_type: str      # "holding" | "input" | "coil" | "discrete"
    address: int            # Register address (0-based)
    point_id: str
    point_name: str = ""
    equipment_id: str = ""
    unit: str = ""
    unit_id: int = 1        # Modbus slave/unit ID
    scale: float = 1.0      # Multiply raw value by this
    offset: float = 0.0     # Add to scaled value
    point_type: PointType = PointType.SENSOR
    data_type: str = "uint16"
    word_order: str = "big"
    byte_order: str = "big"
    poll_interval_seconds: Optional[int] = None   # None → adapter interval
    last_polled: Optional[datetime] = None

    def __post_init__(self):
        if self.data_type not in _REGISTER_COUNT:
            raise ValueError(f"unsupported data_type {self.data_type!r} for {self.point_id}")
        if self.word_order not in ("big", "little") or self.byte_order not in ("big", "little"):
            raise ValueError(f"word_order/byte_order must be big or little for {self.point_id}")

    @property
    def register_count(self) -> int:
        return 1 if self.register_type in ("coil", "discrete") else _REGISTER_COUNT[self.data_type]

    def decode(self, registers: List[int]) -> Optional[float]:
        """Registers (16-bit words) → engineering value, or None if not a finite number."""
        words = [int(w) & 0xFFFF for w in registers[: self.register_count]]
        if len(words) < self.register_count:
            return None
        if self.byte_order == "little":
            words = [((w & 0xFF) << 8) | (w >> 8) for w in words]
        if self.register_count == 1:
            raw = words[0] - 0x10000 if self.data_type == "int16" and words[0] & 0x8000 else words[0]
        else:
            if self.word_order == "little":
                words = words[::-1]
            raw = struct.unpack(_STRUCT[self.data_type], struct.pack(">HH", *words))[0]
            if not math.isfinite(raw):
                return None
        return self.apply_scaling(raw)

    def apply_scaling(self, raw_value) -> float:
        return float(raw_value) * self.scale + self.offset


@dataclass
class ModbusDevice:
    host: str
    port: int = 502
    unit_id: int = 1
    device_name: str = ""
    is_connected: bool = False
    last_seen: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "unit_id": self.unit_id,
            "device_name": self.device_name,
            "is_connected": self.is_connected,
        }


# ═══════════════════════════════════════════════════════════════════════════
# MODBUS ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class ModbusAdapter:
    """
    Async read-only Modbus TCP adapter.

    Read-only by design — no write_register(), no write_coil().
    All data flows state_engine → alarm_engine direction only.

    Example:
        adapter = ModbusAdapter(host="192.168.1.100", port=502)
        await adapter.connect()
        adapter.load_points_from_config(register_map)
        adapter.on_point_update(state_engine.update_point_sync)
        await adapter.start_polling(interval_seconds=30)
    """

    def __init__(
        self,
        host: str = "",
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 5.0,
        transport: str = "tcp",
        serial_port: str = "",
        baudrate: int = 9600,
        parity: str = "N",
        stopbits: int = 1,
        bytesize: int = 8,
    ):
        """transport "tcp" (host/port) or "rtu": Modbus RTU over a serial line
        (RS-485) — meters, gensets, drives and I/O modules that have no Ethernet."""
        self.transport = (transport or "tcp").lower()
        if self.transport not in ("tcp", "rtu"):
            raise ValueError(f"Modbus transport must be tcp or rtu, not {transport!r}")
        if self.transport == "rtu" and not serial_port:
            raise ValueError("Modbus RTU needs serial_port (e.g. /dev/ttyUSB0 or COM3)")
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.serial_port, self.baudrate, self.parity = serial_port, int(baudrate), str(parity).upper()
        self.stopbits, self.bytesize = int(stopbits), int(bytesize)

        self._client: Optional[Any] = None
        self._is_connected = False
        self._points: Dict[str, ModbusPoint] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 30
        self._on_point_update: List[Callable[[BMSDataPoint], None]] = []
        self._unit_kw: Optional[str] = None
        self._last_value: Dict[str, float] = {}
        self._freshness = PointFreshness()
        self._reconnect_delay = 5.0
        self._consecutive_failures = 0

        self.stats = {
            "reads_total": 0,
            "reads_success": 0,
            "reads_failed": 0,
            "reconnects": 0,
            "last_read": None,
        }

        logger.info(f"ModbusAdapter initialized ({self._where()} unit={unit_id})")

    def _where(self) -> str:
        if self.transport == "rtu":
            return f"RTU {self.serial_port} {self.baudrate} {self.bytesize}{self.parity}{self.stopbits}"
        return f"{self.host}:{self.port}"

    async def connect(self) -> bool:
        if not PYMODBUS_AVAILABLE:
            logger.error("pymodbus not installed. Cannot connect.")
            return False
        try:
            if self.transport == "rtu":
                self._client = AsyncModbusSerialClient(
                    port=self.serial_port, baudrate=self.baudrate, parity=self.parity,
                    stopbits=self.stopbits, bytesize=self.bytesize, timeout=self.timeout)
            else:
                self._client = AsyncModbusTcpClient(
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout,
                )
            connected = await self._client.connect()
            if connected:
                self._is_connected = True
                logger.info(f"Modbus connected to {self._where()}")
                return True
            else:
                logger.error(f"Modbus connection failed to {self._where()}")
                return False
        except Exception as e:
            logger.error(f"Modbus connect error: {e}")
            return False

    async def disconnect(self) -> None:
        await self.stop_polling()
        if self._client:
            self._client.close()
            self._client = None
        self._is_connected = False
        logger.info("Modbus adapter disconnected")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _unit_kwarg(self) -> str:
        """pymodbus renamed the unit keyword over releases (unit → slave → device_id).
        Pick whichever the installed client accepts instead of hard-coding one —
        a hard-coded `slave=` raises TypeError on pymodbus ≥ 3.9."""
        if self._unit_kw is None:
            try:
                params = inspect.signature(self._client.read_holding_registers).parameters
            except (TypeError, ValueError):
                params = {}
            self._unit_kw = next((k for k in ("device_id", "slave", "unit") if k in params), "device_id")
        return self._unit_kw

    async def read_register(self, point: ModbusPoint) -> Optional[float]:
        """Read a point's register(s). Returns engineering-unit value or None."""
        if not self._client or not self._is_connected:
            return None
        fn = {"holding": "read_holding_registers", "input": "read_input_registers",
              "coil": "read_coils", "discrete": "read_discrete_inputs"}.get(point.register_type)
        if fn is None:
            logger.warning(f"Unknown register type: {point.register_type}")
            return None
        self.stats["reads_total"] += 1
        try:
            result = await getattr(self._client, fn)(
                address=point.address, count=point.register_count,
                **{self._unit_kwarg(): point.unit_id})
            if result.isError():
                self.stats["reads_failed"] += 1
                logger.debug(f"Modbus read error on {point.point_id}: {result}")
                return None
            if point.register_type in ("coil", "discrete"):
                value = point.apply_scaling(1 if result.bits[0] else 0)
            else:
                value = point.decode(list(result.registers))
            if value is None:
                self.stats["reads_failed"] += 1
                return None
            self.stats["reads_success"] += 1
            self.stats["last_read"] = datetime.now()
            self._consecutive_failures = 0
            return value
        except Exception as e:
            self.stats["reads_failed"] += 1
            self._consecutive_failures += 1
            logger.debug(f"Modbus read exception {point.point_id}: {e}")
            return None

    def _datapoint(self, point: ModbusPoint, value: float, quality: PointQuality) -> BMSDataPoint:
        return BMSDataPoint(
            point_id=point.point_id, name=point.point_name, value=value, unit=point.unit,
            timestamp=datetime.now(timezone.utc), source="modbus", equipment_id=point.equipment_id,
            point_type=point.point_type, quality=quality)

    async def read_point(self, point: ModbusPoint) -> Optional[BMSDataPoint]:
        value = await self.read_register(point)
        if value is None:
            return None
        self._last_value[point.point_id] = value
        self._freshness.mark_ok(point.point_id)
        return self._datapoint(point, value, PointQuality.GOOD)

    def _interval(self, point: ModbusPoint) -> float:
        return float(point.poll_interval_seconds or self._poll_interval)

    def _due(self, point: ModbusPoint, now: datetime) -> bool:
        return point.last_polled is None or \
            (now - point.last_polled).total_seconds() >= self._interval(point) - 0.5

    async def read_all_points(self, only_due: bool = False) -> List[BMSDataPoint]:
        results = []
        now = datetime.now()
        for point in self._points.values():
            if only_due and not self._due(point, now):
                continue
            point.last_polled = now
            try:
                dp = await self.read_point(point)
                if dp:
                    results.append(dp)
            except Exception as e:
                logger.error(f"Error reading {point.point_id}: {e}")
        # Points that stopped answering go STALE once (last value, clearly flagged).
        for pid in self._freshness.newly_stale({p.point_id: self._interval(p) for p in self._points.values()}):
            p = self._points[pid]
            if pid in self._last_value:
                results.append(self._datapoint(p, self._last_value[pid], PointQuality.STALE))
            logger.warning(f"Modbus point {pid} is stale (no good read for "
                           f"{self._freshness.stale_factor:g}× its poll interval)")
        return results

    async def _ensure_connected(self) -> bool:
        """Reconnect with exponential backoff after the link drops."""
        client_up = bool(self._client is not None and getattr(self._client, "connected", self._is_connected))
        if self._is_connected and client_up and self._consecutive_failures < max(3, len(self._points)):
            return True
        self._is_connected = False
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        ok = await self.connect()
        self.stats["reconnects"] += 1
        if ok:
            self._reconnect_delay = 5.0
            self._consecutive_failures = 0
            return True
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 300.0)
        return False

    def add_point(self, point: ModbusPoint) -> None:
        self._points[point.point_id] = point
        self._freshness.register(point.point_id)

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        """Load register map from config dict: `registers`, plus any `io_modules`
        (Modbus I/O boxes wired to dumb equipment — see io_modules.py)."""
        count = 0
        default_unit_id = config.get("unit_id", self.unit_id)
        for reg in modbus_register_entries(config):
            try:
                self.add_point(_point_from_config(reg, default_unit_id))
                count += 1
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid register config, skipping: {e}")
        logger.info(f"Loaded {count} Modbus register configurations")
        return count

    async def start_polling(self, interval_seconds: int = 30) -> None:
        if self._poll_task and not self._poll_task.done():
            logger.warning("Polling already active")
            return
        self._poll_interval = interval_seconds
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"Modbus polling started every {interval_seconds}s")

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        tick = max(1.0, min([self._poll_interval] + [
            float(p.poll_interval_seconds) for p in self._points.values() if p.poll_interval_seconds]))
        while True:
            try:
                await self._ensure_connected()
                # Read even when the link is down: failed reads age points into STALE.
                points = await self.read_all_points(only_due=True)
                for point in points:
                    for cb in self._on_point_update:
                        try:
                            result = cb(point)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Modbus poll error: {e}")
            await asyncio.sleep(tick)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "is_connected": self._is_connected,
            "points_configured": len(self._points),
            "stale_points": self._freshness.stale_points,
            "polling_active": self._poll_task is not None and not self._poll_task.done(),
        }


def modbus_register_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every register a Modbus config describes: the explicit `registers` plus the
    expanded `io_modules` (template + what is wired to each channel)."""
    regs = list(config.get("registers") or [])
    if config.get("io_modules"):
        from agent_commercial.io_modules import expand
        regs += expand(config["io_modules"])
    return regs


def modbus_adapter_from_config(cfg: Dict[str, Any]) -> "ModbusAdapter":
    return ModbusAdapter(host=cfg.get("host", "127.0.0.1"), port=cfg.get("port", 502), unit_id=cfg.get("unit_id", 1),
                         timeout=float(cfg.get("timeout", 5.0)), transport=cfg.get("transport", "tcp"),
                         serial_port=cfg.get("serial_port", ""), baudrate=cfg.get("baudrate", 9600),
                         parity=cfg.get("parity", "N"), stopbits=cfg.get("stopbits", 1), bytesize=cfg.get("bytesize", 8))


def _point_from_config(reg: Dict[str, Any], default_unit_id: int) -> ModbusPoint:
    return ModbusPoint(
        register_type=reg["register_type"],
        address=int(reg["address"]),
        point_id=reg["point_id"],
        point_name=reg.get("point_name", reg["point_id"]),
        equipment_id=reg.get("equipment_id", ""),
        unit=reg.get("unit", ""),
        unit_id=int(reg.get("unit_id", default_unit_id)),
        scale=float(reg.get("scale", 1.0)),
        offset=float(reg.get("offset", 0.0)),
        data_type=str(reg.get("data_type", "uint16")).lower(),
        word_order=str(reg.get("word_order", "big")).lower(),
        byte_order=str(reg.get("byte_order", "big")).lower(),
        poll_interval_seconds=int(reg["poll_interval"]) if reg.get("poll_interval") else None,
    )
