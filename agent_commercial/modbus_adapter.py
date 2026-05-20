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
            }
        ]
    }
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import warnings

try:
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    warnings.warn("pymodbus not installed. Run: pip install pymodbus")

from agent_commercial.bms_data_model import (
    BMSDataPoint,
    PointType,
    PointQuality,
)

logger = logging.getLogger("arvis.bms.modbus")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ModbusPoint:
    """Configuration for a single Modbus register point."""
    register_type: str      # "holding" | "input" | "coil"
    address: int            # Register address (0-based)
    point_id: str
    point_name: str = ""
    equipment_id: str = ""
    unit: str = ""
    unit_id: int = 1        # Modbus slave/unit ID
    scale: float = 1.0      # Multiply raw value by this
    offset: float = 0.0     # Add to scaled value
    point_type: PointType = PointType.SENSOR
    poll_interval_seconds: int = 30
    last_polled: Optional[datetime] = None

    def apply_scaling(self, raw_value: int) -> float:
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
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout

        self._client: Optional[Any] = None
        self._is_connected = False
        self._points: Dict[str, ModbusPoint] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 30
        self._on_point_update: List[Callable[[BMSDataPoint], None]] = []

        self.stats = {
            "reads_total": 0,
            "reads_success": 0,
            "reads_failed": 0,
            "last_read": None,
        }

        logger.info(f"ModbusAdapter initialized ({host}:{port} unit={unit_id})")

    async def connect(self) -> bool:
        if not PYMODBUS_AVAILABLE:
            logger.error("pymodbus not installed. Cannot connect.")
            return False
        try:
            self._client = AsyncModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
            )
            connected = await self._client.connect()
            if connected:
                self._is_connected = True
                logger.info(f"Modbus connected to {self.host}:{self.port}")
                return True
            else:
                logger.error(f"Modbus connection failed to {self.host}:{self.port}")
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

    async def read_register(self, point: ModbusPoint) -> Optional[float]:
        """Read a single Modbus register. Returns engineering-unit value or None."""
        if not self._client or not self._is_connected:
            return None

        try:
            if point.register_type == "holding":
                result = await self._client.read_holding_registers(
                    address=point.address,
                    count=1,
                    slave=point.unit_id,
                )
            elif point.register_type == "input":
                result = await self._client.read_input_registers(
                    address=point.address,
                    count=1,
                    slave=point.unit_id,
                )
            elif point.register_type == "coil":
                result = await self._client.read_coils(
                    address=point.address,
                    count=1,
                    slave=point.unit_id,
                )
            else:
                logger.warning(f"Unknown register type: {point.register_type}")
                return None

            if result.isError():
                self.stats["reads_failed"] += 1
                self.stats["reads_total"] += 1
                logger.debug(f"Modbus read error on {point.point_id}: {result}")
                return None

            raw = result.registers[0] if hasattr(result, "registers") else int(result.bits[0])
            self.stats["reads_success"] += 1
            self.stats["reads_total"] += 1
            self.stats["last_read"] = datetime.now()
            return point.apply_scaling(raw)

        except Exception as e:
            self.stats["reads_failed"] += 1
            self.stats["reads_total"] += 1
            logger.debug(f"Modbus read exception {point.point_id}: {e}")
            return None

    async def read_point(self, point: ModbusPoint) -> Optional[BMSDataPoint]:
        value = await self.read_register(point)
        if value is None:
            return None

        return BMSDataPoint(
            point_id=point.point_id,
            name=point.point_name,
            value=value,
            unit=point.unit,
            timestamp=datetime.now(),
            source="modbus",
            equipment_id=point.equipment_id,
            point_type=point.point_type,
            quality=PointQuality.GOOD,
        )

    async def read_all_points(self) -> List[BMSDataPoint]:
        results = []
        for point in self._points.values():
            try:
                dp = await self.read_point(point)
                if dp:
                    results.append(dp)
                    point.last_polled = datetime.now()
            except Exception as e:
                logger.error(f"Error reading {point.point_id}: {e}")
        return results

    def add_point(self, point: ModbusPoint) -> None:
        self._points[point.point_id] = point

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        """Load register map from config dict."""
        count = 0
        default_unit_id = config.get("unit_id", self.unit_id)
        for reg in config.get("registers", []):
            try:
                point = ModbusPoint(
                    register_type=reg["register_type"],
                    address=reg["address"],
                    point_id=reg["point_id"],
                    point_name=reg.get("point_name", reg["point_id"]),
                    equipment_id=reg.get("equipment_id", ""),
                    unit=reg.get("unit", ""),
                    unit_id=reg.get("unit_id", default_unit_id),
                    scale=float(reg.get("scale", 1.0)),
                    offset=float(reg.get("offset", 0.0)),
                )
                self.add_point(point)
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
        while True:
            try:
                points = await self.read_all_points()
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
            await asyncio.sleep(self._poll_interval)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "is_connected": self._is_connected,
            "points_configured": len(self._points),
            "polling_active": self._poll_task is not None and not self._poll_task.done(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MODBUS SIMULATOR (development / testing)
# ═══════════════════════════════════════════════════════════════════════════

class ModbusSimulatorAdapter:
    """
    In-process simulator for development without Modbus hardware.
    Generates realistic register values with drift for testing.
    """

    def __init__(self):
        self._points: Dict[str, ModbusPoint] = {}
        self._sim_values: Dict[str, float] = {}
        self._is_connected = False
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 30
        self._on_point_update: List[Callable] = []
        self._tick = 0

    async def connect(self) -> bool:
        self._setup_defaults()
        self._is_connected = True
        logger.info("Modbus simulator connected")
        return True

    async def disconnect(self) -> None:
        await self.stop_polling()
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _setup_defaults(self) -> None:
        import math
        self._sim_values = {
            "AHU-03/SAT": 14.0,
            "AHU-03/RAT": 24.0,
            "AHU-03/SF_SPD": 70.0,
            "AHU-03/FLT_DP": 120.0,
            "CH-03/CHWST": 7.0,
            "CH-03/KW": 200.0,
            "METER-02/KW": 450.0,
        }

    def add_point(self, point: ModbusPoint) -> None:
        self._points[point.point_id] = point
        if point.point_id not in self._sim_values:
            self._sim_values[point.point_id] = 0.0

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        count = 0
        default_unit_id = config.get("unit_id", 1)
        for reg in config.get("registers", []):
            try:
                point = ModbusPoint(
                    register_type=reg["register_type"],
                    address=reg["address"],
                    point_id=reg["point_id"],
                    point_name=reg.get("point_name", reg["point_id"]),
                    equipment_id=reg.get("equipment_id", ""),
                    unit=reg.get("unit", ""),
                    unit_id=reg.get("unit_id", default_unit_id),
                    scale=float(reg.get("scale", 1.0)),
                    offset=float(reg.get("offset", 0.0)),
                )
                self.add_point(point)
                count += 1
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid register config, skipping: {e}")
        return count

    def _simulate_tick(self) -> None:
        import random
        self._tick += 1
        for key in self._sim_values:
            val = self._sim_values[key]
            # Small random walk
            self._sim_values[key] = val + random.uniform(-0.5, 0.5)
            # Filter DP slowly creeps up
            if "FLT_DP" in key:
                self._sim_values[key] = max(50, val + random.uniform(0, 0.3))

    async def read_all_points(self) -> List[BMSDataPoint]:
        self._simulate_tick()
        results = []
        for point in self._points.values():
            value = self._sim_values.get(point.point_id, 0.0)
            results.append(BMSDataPoint(
                point_id=point.point_id,
                name=point.point_name,
                value=value,
                unit=point.unit,
                timestamp=datetime.now(),
                source="modbus_sim",
                equipment_id=point.equipment_id,
                quality=PointQuality.GOOD,
            ))
        return results

    async def start_polling(self, interval_seconds: int = 30) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        self._poll_interval = interval_seconds
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                points = await self.read_all_points()
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
                logger.error(f"Sim poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "is_connected": self._is_connected,
            "points_configured": len(self._points),
            "polling_active": self._poll_task is not None and not self._poll_task.done(),
            "tick": self._tick,
        }
