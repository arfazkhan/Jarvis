"""
BACnet/IP Adapter (async-native) — bacpypes3 implementation
============================================================

Read-only BACnet client for ARVIS BMS integration.

Fully async — no threads, no run_in_executor, no blocking.
All operations are proper coroutines.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from bacpypes3.app import Application
from bacpypes3.primitivedata import ObjectIdentifier
from bacpypes3.ipv4.app import BBMDApplication
from bacpypes3.pdu import Address
from bacpypes3.object import DeviceObject

from agent_commercial.bms_data_model import (
    BMSDataPoint,
    PointType,
    PointQuality,
    Alarm,
    AlarmSeverity,
    AlarmState,
)

logger = logging.getLogger("arvis.bms.bacnet3")


class BACnetObjectType(Enum):
    ANALOG_INPUT = "analogInput"
    ANALOG_OUTPUT = "analogOutput"
    ANALOG_VALUE = "analogValue"
    BINARY_INPUT = "binaryInput"
    BINARY_OUTPUT = "binaryOutput"
    BINARY_VALUE = "binaryValue"
    MULTI_STATE_INPUT = "multiStateInput"
    DEVICE = "device"


@dataclass
class BACnetDevice:
    device_id: int
    device_name: str
    address: str
    vendor_name: str = ""
    model_name: str = ""
    object_count: int = 0
    is_connected: bool = False
    last_seen: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "address": self.address,
            "vendor_name": self.vendor_name,
            "model_name": self.model_name,
            "object_count": self.object_count,
            "is_connected": self.is_connected,
        }


@dataclass
class BACnetPoint:
    device_id: int
    object_type: str
    object_instance: int
    property_name: str = "presentValue"

    point_id: str = ""
    point_name: str = ""
    equipment_id: str = ""
    unit: str = ""
    point_type: PointType = PointType.SENSOR
    poll_interval_seconds: int = 30
    last_polled: Optional[datetime] = None

    @property
    def bacnet_address(self) -> str:
        return f"{self.object_type}:{self.object_instance}"


class BACnetAdapter:
    """
    Async-native BACnet/IP adapter using bacpypes3.
    No threads, no run_in_executor — fully async/await.
    """

    def __init__(
        self,
        local_address: Optional[str] = None,
        port: int = 47808,
        device_id: int = 999,
    ):
        self.local_address = local_address
        self.port = port
        self.device_id = device_id

        self._app: Optional[Application] = None
        self._is_connected = False
        self._devices: Dict[int, BACnetDevice] = {}
        self._points: Dict[str, BACnetPoint] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 30
        self._on_point_update: List[Callable[[BMSDataPoint], None]] = []
        self._on_alarm: List[Callable[[Alarm], None]] = []

        self.stats = {
            "reads_total": 0,
            "reads_success": 0,
            "reads_failed": 0,
            "last_read": None,
        }

        logger.info(f"BACnetAdapter initialized (port={port}, device_id={device_id})")

    async def connect(self) -> bool:
        try:
            addr = self.local_address or "0.0.0.0"
            bind_addr = f"{addr}:{self.port}"
            logger.info(f"Binding BACnet app to {bind_addr}")

            local_device = DeviceObject(
                objectIdentifier=("device", self.device_id),
                objectName="ARVIS-BACnet-Client",
                vendorIdentifier=15,
            )

            self._app = BBMDApplication(local_device, Address(bind_addr))
            self._is_connected = True
            logger.info("BACnet adapter connected")
            return True

        except Exception as e:
            logger.error(f"BACnet connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        await self.stop_polling()
        self._app = None
        self._is_connected = False
        logger.info("BACnet adapter disconnected")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def discover_devices(self, timeout_seconds: int = 5) -> List[BACnetDevice]:
        if not self._app:
            logger.warning("Not connected")
            return []

        logger.info(f"Sending WhoIs (timeout={timeout_seconds}s)...")
        self._app.whois()
        await asyncio.sleep(timeout_seconds)

        discovered = list(self._devices.values())
        logger.info(f"Discovered {len(discovered)} devices")
        return discovered

    async def read_property(
        self,
        device_address: str,
        object_type: str,
        object_instance: int,
        property_name: str = "presentValue",
        timeout: float = 5.0,
    ) -> Optional[Any]:
        if not self._app:
            return None

        try:
            addr = Address(device_address)
            obj_id = ObjectIdentifier(object_type, object_instance)

            value = await asyncio.wait_for(
                self._app.read_property(addr, obj_id, property_name),
                timeout=timeout,
            )

            self.stats["reads_total"] += 1
            self.stats["reads_success"] += 1
            self.stats["last_read"] = datetime.now()
            return value

        except asyncio.TimeoutError:
            self.stats["reads_total"] += 1
            self.stats["reads_failed"] += 1
            logger.debug(f"Read timeout: {device_address} {object_type}:{object_instance}")
            return None
        except Exception as e:
            self.stats["reads_total"] += 1
            self.stats["reads_failed"] += 1
            logger.debug(f"Read error: {e}")
            return None

    async def read_point(self, point_config: BACnetPoint) -> Optional[BMSDataPoint]:
        device = self._devices.get(point_config.device_id)
        if not device:
            logger.warning(f"Device {point_config.device_id} not found")
            return None

        value = await self.read_property(
            device_address=device.address,
            object_type=point_config.object_type,
            object_instance=point_config.object_instance,
            property_name=point_config.property_name,
        )

        if value is None:
            return None

        try:
            float_val = float(value)
        except (TypeError, ValueError):
            float_val = 0.0

        return BMSDataPoint(
            point_id=point_config.point_id,
            name=point_config.point_name,
            value=float_val,
            unit=point_config.unit,
            timestamp=datetime.now(),
            source="bacnet",
            equipment_id=point_config.equipment_id,
            point_type=point_config.point_type,
            quality=PointQuality.GOOD,
            bacnet_device_id=point_config.device_id,
            bacnet_object_type=point_config.object_type,
            bacnet_object_instance=point_config.object_instance,
        )

    async def read_all_points(self) -> List[BMSDataPoint]:
        results = []
        for config in self._points.values():
            try:
                point = await self.read_point(config)
                if point:
                    results.append(point)
                    config.last_polled = datetime.now()
            except Exception as e:
                logger.error(f"Error reading {config.point_id}: {e}")
        return results

    def add_point(self, config: BACnetPoint) -> None:
        self._points[config.point_id] = config

    def remove_point(self, point_id: str) -> bool:
        if point_id in self._points:
            del self._points[point_id]
            return True
        return False

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        count = 0
        for point_cfg in config.get("points", []):
            try:
                point = BACnetPoint(
                    device_id=point_cfg["device_id"],
                    object_type=point_cfg["object_type"],
                    object_instance=point_cfg["object_instance"],
                    point_id=point_cfg.get("point_id", f"point_{count}"),
                    point_name=point_cfg.get("name", ""),
                    equipment_id=point_cfg.get("equipment_id", ""),
                    unit=point_cfg.get("unit", ""),
                )
                self.add_point(point)
                count += 1
            except KeyError as e:
                logger.warning(f"Invalid point config, missing {e}")
        logger.info(f"Loaded {count} point configurations")
        return count

    async def start_polling(self, interval_seconds: int = 30) -> None:
        if self._poll_task and not self._poll_task.done():
            logger.warning("Polling already active")
            return

        self._poll_interval = interval_seconds
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"Started polling every {interval_seconds}s")

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            logger.info("Stopped polling")

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
                logger.error(f"Poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def on_alarm(self, callback: Callable[[Alarm], None]) -> None:
        self._on_alarm.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "is_connected": self.is_connected,
            "devices_discovered": len(self._devices),
            "points_configured": len(self._points),
            "polling_active": self._poll_task is not None and not self._poll_task.done(),
        }


class BACnetSimulatorAdapter:
    """
    In-process simulator for development without BACnet hardware.
    Generates realistic BMS data with configurable points.
    """

    def __init__(self):
        self._devices: Dict[int, BACnetDevice] = {}
        self._points: Dict[str, BACnetPoint] = {}
        self._sim_values: Dict[str, float] = {}
        self._is_connected = False
        self._poll_task: Optional[asyncio.Task] = None
        self._on_point_update: List[Callable] = []

    async def connect(self) -> bool:
        self._setup_simulated_devices()
        self._is_connected = True
        logger.info("Simulator adapter connected")
        return True

    async def disconnect(self) -> None:
        await self.stop_polling()
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def _setup_simulated_devices(self) -> None:
        self._devices[260001] = BACnetDevice(
            device_id=260001,
            device_name="ARVIS-SIM-CHiller",
            address="127.0.0.1:47808",
            vendor_name="ARVIS",
            model_name="Simulator v1.0",
            is_connected=True,
        )
        self._sim_values = {
            "CH-01/CHWST": 7.0,
            "CH-01/CHWRT": 12.0,
            "CH-01/KW": 240.0,
            "CH-01/LOAD": 65.0,
            "CH-01/STATUS": 1.0,
            "CH-02/CHWST": 7.5,
            "CH-02/KW": 180.0,
            "AHU-01/SAT": 14.0,
            "AHU-01/RAT": 24.0,
            "AHU-01/SF_SPD": 75.0,
            "AHU-02/SAT": 14.5,
            "AHU-02/RAT": 23.5,
            "METER/KW": 620.0,
            "WTR-01/TOTAL_M3": 1250.0,
            "WTR-01/FLOW_LPM": 12.5,
            "WTR-02/TOTAL_M3": 450.0,
            "WTR-02/FLOW_LPM": 3.2,
        }

    async def discover_devices(self, timeout_seconds: int = 1) -> List[BACnetDevice]:
        await asyncio.sleep(0.1)
        return list(self._devices.values())

    def add_point(self, config: BACnetPoint) -> None:
        self._points[config.point_id] = config

    def remove_point(self, point_id: str) -> bool:
        if point_id in self._points:
            del self._points[point_id]
            return True
        return False

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        count = 0
        for point_cfg in config.get("points", []):
            try:
                point = BACnetPoint(
                    device_id=point_cfg["device_id"],
                    object_type=point_cfg["object_type"],
                    object_instance=point_cfg["object_instance"],
                    point_id=point_cfg.get("point_id", f"point_{count}"),
                    point_name=point_cfg.get("name", ""),
                    equipment_id=point_cfg.get("equipment_id", ""),
                    unit=point_cfg.get("unit", ""),
                )
                self.add_point(point)
                count += 1
            except KeyError:
                pass
        logger.info(f"Simulator: loaded {count} point configs")
        return count

    async def read_point(self, point_config: BACnetPoint) -> Optional[BMSDataPoint]:
        import random

        base = self._sim_values.get(point_config.point_id, 50.0)
        if "KW" in point_config.point_id:
            val = base * (1 + random.uniform(-0.05, 0.05))
        elif "TOTAL_M3" in point_config.point_id:
            # Meters are cumulative, they should only go up
            increment = random.uniform(0.01, 0.05)
            self._sim_values[point_config.point_id] = base + increment
            val = base + increment
        elif "FLOW_LPM" in point_config.point_id:
            val = base * (1 + random.uniform(-0.1, 0.1))
        elif "SAT" in point_config.point_id or "CHWST" in point_config.point_id:
            val = base + random.uniform(-0.5, 0.5)
        else:
            val = base + random.uniform(-1, 1)

        return BMSDataPoint(
            point_id=point_config.point_id,
            name=point_config.point_name,
            value=round(val, 2),
            unit=point_config.unit,
            timestamp=datetime.now(),
            source="simulator",
            equipment_id=point_config.equipment_id,
            point_type=point_config.point_type,
            quality=PointQuality.GOOD,
        )

    async def read_all_points(self) -> List[BMSDataPoint]:
        results = []
        for config in self._points.values():
            point = await self.read_point(config)
            if point:
                results.append(point)
        return results

    def on_point_update(self, callback: Callable) -> None:
        self._on_point_update.append(callback)

    async def start_polling(self, interval_seconds: int = 5) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        self._poll_task = asyncio.create_task(self._poll_loop(interval_seconds))
        logger.info(f"Simulator polling started every {interval_seconds}s")

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self, interval: int) -> None:
        import random

        while True:
            try:
                for k in self._sim_values:
                    drift = random.uniform(-0.5, 0.5)
                    self._sim_values[k] = max(0, self._sim_values[k] + drift)

                points = await self.read_all_points()
                for point in points:
                    for cb in self._on_point_update:
                        try:
                            result = cb(point)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Simulator poll error: {e}")
            await asyncio.sleep(interval)
