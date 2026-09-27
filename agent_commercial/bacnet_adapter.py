"""
BACnet/IP Adapter (async-native) — bacpypes3 implementation
============================================================

Read-only BACnet client for ARVIS BMS integration.

Fully async — no threads, no run_in_executor, no blocking.
All operations are proper coroutines.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from bacpypes3.app import Application
from bacpypes3.basetypes import PropertyIdentifier
from bacpypes3.primitivedata import ObjectIdentifier
from bacpypes3.ipv4.app import BBMDApplication
from bacpypes3.pdu import Address
from bacpypes3.object import DeviceObject

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import (
    BMSDataPoint,
    PointType,
    PointQuality,
    Alarm,
    AlarmSeverity,
    AlarmState,
)

logger = logging.getLogger("arvis.bms.bacnet3")


# Text forms of BACnet binary present values (BinaryPV enumerations).
_BINARY_TEXT = {"active": 1.0, "inactive": 0.0, "on": 1.0, "off": 0.0,
                "true": 1.0, "false": 0.0}


def coerce_numeric(value: Any) -> Optional[float]:
    """Convert a BACnet present value to a float, or None if it has no honest
    numeric meaning. Never substitutes a default — the old `except: 0.0` turned
    unreadable values into a fake GOOD zero."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _BINARY_TEXT.get(str(value).strip().lower())
    return f if math.isfinite(f) else None


def quality_from_status_flags(flags: Any) -> PointQuality:
    """Map BACnet StatusFlags (inAlarm, fault, overridden, outOfService) to quality.

    fault or outOfService → BAD (the value is not a live measurement);
    overridden → OVERRIDDEN; flags unavailable → UNCERTAIN; else GOOD.
    """
    if flags is None:
        return PointQuality.UNCERTAIN
    try:
        bits = [int(b) for b in flags]
    except (TypeError, ValueError):
        return PointQuality.UNCERTAIN
    if len(bits) < 4:
        return PointQuality.UNCERTAIN
    _in_alarm, fault, overridden, out_of_service = bits[:4]
    if fault or out_of_service:
        return PointQuality.BAD
    if overridden:
        return PointQuality.OVERRIDDEN
    return PointQuality.GOOD


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
    poll_interval_seconds: Optional[int] = None    # None → adapter interval
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
        check_status_flags: bool = True,
        max_per_request: int = 20,
        rediscover_interval_s: float = 600.0,
        read_timeout_s: float = 5.0,
    ):
        self.local_address = local_address
        self.port = port
        self.device_id = device_id
        # Read statusFlags alongside presentValue so faulted / out-of-service /
        # overridden points are marked, not trusted as GOOD. With
        # ReadPropertyMultiple both come back in the same request.
        self.check_status_flags = check_status_flags
        self.max_per_request = max(1, int(max_per_request))
        self.rediscover_interval_s = rediscover_interval_s
        self.read_timeout_s = read_timeout_s
        self._invalid_warned: set = set()
        self._rpm_unsupported: set = set()        # device ids that rejected RPM
        self._freshness = PointFreshness()
        self._last_value: Dict[str, float] = {}
        self._last_discovery = 0.0

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
            "reads_non_numeric": 0,
            "rpm_requests": 0,
            "rediscoveries": 0,
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

        logger.info(f"Sending Who-Is (timeout={timeout_seconds}s)...")
        # Previously called self._app.whois() (which does not exist in bacpypes3)
        # and then returned _devices — a dict nothing ever populated, so discovery
        # always found zero devices and every subsequent point read was rejected
        # as an unknown device. bacpypes3's who_is() broadcasts Who-Is AND returns
        # the I-Am responses; register each discovered device so reads resolve.
        i_ams = []
        try:
            i_ams = await asyncio.wait_for(self._app.who_is(), timeout=timeout_seconds + 1)
        except asyncio.TimeoutError:
            logger.warning("Who-Is timed out with no I-Am responses")
        except Exception as e:
            logger.warning(f"Who-Is failed: {e}")

        for iam in (i_ams or []):
            try:
                dev_ident = getattr(iam, "iAmDeviceIdentifier", None)
                if dev_ident is None:
                    continue
                # ObjectIdentifier behaves like ('device', instance)
                dev_id = int(dev_ident[1])
                addr = str(getattr(iam, "pduSource", "") or "")
                self._devices[dev_id] = BACnetDevice(
                    device_id=dev_id,
                    device_name=f"device-{dev_id}",
                    address=addr,
                    vendor_name=str(getattr(iam, "vendorID", "") or ""),
                    is_connected=True,
                )
            except Exception as e:
                logger.debug(f"Skipping malformed I-Am response: {e}")
                continue

        discovered = list(self._devices.values())
        self._last_discovery = time.monotonic()
        logger.info(f"Discovered {len(discovered)} BACnet devices")
        return discovered

    def missing_devices(self) -> List[int]:
        """Configured device ids that have not answered Who-Is."""
        return sorted({p.device_id for p in self._points.values()} - set(self._devices))

    async def maybe_rediscover(self) -> bool:
        """Re-run Who-Is when configured devices are missing (devices reboot, come
        online late, or change address). Rate-limited by rediscover_interval_s."""
        if not self.missing_devices():
            return False
        if time.monotonic() - self._last_discovery < self.rediscover_interval_s:
            return False
        self.stats["rediscoveries"] += 1
        await self.discover_devices()
        return True

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
            # One tuple argument. ObjectIdentifier(type, instance) raises ValueError
            # in bacpypes3, and the except below swallowed it — so every single
            # read used to fail silently.
            obj_id = ObjectIdentifier((object_type, object_instance))

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
            # Warning (once per object), not debug: a debug-level swallow hid the
            # ObjectIdentifier bug that made every read fail.
            key = f"{device_address}/{object_type}:{object_instance}/{property_name}"
            if key not in self._invalid_warned:
                self._invalid_warned.add(key)
                logger.warning(f"BACnet read failed {key}: {type(e).__name__}: {e}")
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

        flags = None
        if self.check_status_flags:
            flags = await self.read_property(
                device_address=device.address,
                object_type=point_config.object_type,
                object_instance=point_config.object_instance,
                property_name="statusFlags",
            )
        return self._make_point(point_config, value, flags)

    def _make_point(self, cfg: BACnetPoint, value: Any, flags: Any,
                    quality: Optional[PointQuality] = None) -> Optional[BMSDataPoint]:
        float_val = coerce_numeric(value)
        if float_val is None:
            # No honest numeric reading — skip it rather than invent one.
            self.stats["reads_non_numeric"] += 1
            if cfg.point_id not in self._invalid_warned:
                self._invalid_warned.add(cfg.point_id)
                logger.warning(f"{cfg.point_id}: non-numeric present value {value!r} — not recorded")
            return None
        if quality is None:
            quality = quality_from_status_flags(flags) if self.check_status_flags else PointQuality.GOOD
        self._last_value[cfg.point_id] = float_val
        self._freshness.mark_ok(cfg.point_id)
        return BMSDataPoint(
            point_id=cfg.point_id,
            name=cfg.point_name,
            value=float_val,
            unit=cfg.unit,
            timestamp=datetime.now(timezone.utc),
            source="bacnet",
            equipment_id=cfg.equipment_id,
            point_type=cfg.point_type,
            quality=quality,
            bacnet_device_id=cfg.device_id,
            bacnet_object_type=cfg.object_type,
            bacnet_object_instance=cfg.object_instance,
        )

    async def _read_device_rpm(self, device: BACnetDevice, cfgs: List[BACnetPoint]) -> List[BMSDataPoint]:
        """ReadPropertyMultiple: presentValue (+ statusFlags) for up to
        max_per_request objects per request. Raises if the device rejects RPM."""
        out: List[BMSDataPoint] = []
        pv_sf = PropertyIdentifier("statusFlags")
        for i in range(0, len(cfgs), self.max_per_request):
            chunk = cfgs[i:i + self.max_per_request]
            params, keys = [], []
            for c in chunk:
                oid = ObjectIdentifier((c.object_type, c.object_instance))
                props = [c.property_name] + (["statusFlags"] if self.check_status_flags else [])
                params.append((oid, props))
                keys.append((str(oid), str(PropertyIdentifier(c.property_name))))
            self.stats["rpm_requests"] += 1
            self.stats["reads_total"] += len(chunk)
            try:
                rows = await asyncio.wait_for(
                    self._app.read_property_multiple(Address(device.address), params),
                    timeout=self.read_timeout_s)
            except asyncio.TimeoutError:
                self.stats["reads_failed"] += len(chunk)
                continue
            values = {(str(oid), str(prop)): val for oid, prop, _idx, val in (rows or [])}
            for c, (oid_s, prop_s) in zip(chunk, keys):
                pv = values.get((oid_s, prop_s))
                if pv is None:
                    self.stats["reads_failed"] += 1
                    continue
                dp = self._make_point(c, pv, values.get((oid_s, str(pv_sf))))
                if dp is not None:
                    self.stats["reads_success"] += 1
                    out.append(dp)
        self.stats["last_read"] = datetime.now()
        return out

    def _interval(self, cfg: BACnetPoint) -> float:
        return float(cfg.poll_interval_seconds or self._poll_interval)

    async def read_all_points(self, only_due: bool = False) -> List[BMSDataPoint]:
        results: List[BMSDataPoint] = []
        now = datetime.now()
        by_device: Dict[int, List[BACnetPoint]] = {}
        for cfg in self._points.values():
            if only_due and cfg.last_polled is not None and \
                    (now - cfg.last_polled).total_seconds() < self._interval(cfg) - 0.5:
                continue
            cfg.last_polled = now
            by_device.setdefault(cfg.device_id, []).append(cfg)

        for dev_id, cfgs in by_device.items():
            device = self._devices.get(dev_id)
            if device is None:
                continue                      # not discovered yet — maybe_rediscover() retries
            if dev_id not in self._rpm_unsupported:
                try:
                    results.extend(await self._read_device_rpm(device, cfgs))
                    continue
                except Exception as e:
                    self._rpm_unsupported.add(dev_id)
                    logger.info(f"BACnet device {dev_id} rejected ReadPropertyMultiple ({e}); "
                                f"using single reads")
            for cfg in cfgs:
                try:
                    point = await self.read_point(cfg)
                    if point:
                        results.append(point)
                except Exception as e:
                    logger.error(f"Error reading {cfg.point_id}: {e}")

        # Points that stopped answering go STALE once (last value, clearly flagged).
        for pid in self._freshness.newly_stale({c.point_id: self._interval(c) for c in self._points.values()}):
            cfg = self._points[pid]
            if pid in self._last_value:
                results.append(BMSDataPoint(
                    point_id=pid, name=cfg.point_name, value=self._last_value[pid], unit=cfg.unit,
                    timestamp=datetime.now(timezone.utc), source="bacnet",
                    equipment_id=cfg.equipment_id, point_type=cfg.point_type,
                    quality=PointQuality.STALE, bacnet_device_id=cfg.device_id,
                    bacnet_object_type=cfg.object_type, bacnet_object_instance=cfg.object_instance))
            logger.warning(f"BACnet point {pid} is stale (no good read for "
                           f"{self._freshness.stale_factor:g}× its poll interval)")
        return results

    def add_point(self, config: BACnetPoint) -> None:
        self._points[config.point_id] = config
        self._freshness.register(config.point_id)

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
                    property_name=point_cfg.get("property", "presentValue"),
                    point_id=point_cfg.get("point_id", f"point_{count}"),
                    point_name=point_cfg.get("name", ""),
                    equipment_id=point_cfg.get("equipment_id", ""),
                    unit=point_cfg.get("unit", ""),
                    poll_interval_seconds=(int(point_cfg["poll_interval"])
                                           if point_cfg.get("poll_interval") else None),
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
        tick = max(1.0, min([float(self._poll_interval)] + [
            float(p.poll_interval_seconds) for p in self._points.values() if p.poll_interval_seconds]))
        while True:
            try:
                await self.maybe_rediscover()
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
                logger.error(f"Poll error: {e}")
            await asyncio.sleep(tick)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def on_alarm(self, callback: Callable[[Alarm], None]) -> None:
        self._on_alarm.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "is_connected": self.is_connected,
            "devices_discovered": len(self._devices),
            "devices_missing": self.missing_devices(),
            "rpm_unsupported_devices": sorted(self._rpm_unsupported),
            "stale_points": self._freshness.stale_points,
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
        self._sim_value_timestamps: Dict[str, float] = {}
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

    def get_point_last_update_epoch(self, point_id: str) -> Optional[float]:
        return self._sim_value_timestamps.get(point_id)

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
        _now = time.time()
        self._sim_value_timestamps = {k: _now for k in self._sim_values}

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

    def register_dynamic_point(self, point_id: str, cadence_seconds: float) -> None:
        """Record a runtime-added poll entry (used by ARVIS Discovery Agent).

        The sim has no real poller, so we stash the cadence in a side dict so
        tests/inspectors can see what's been onboarded. The production
        BACnet/IP adapter will wire this into the actual scheduler.
        """
        if not hasattr(self, "_dynamic_poll_registry"):
            self._dynamic_poll_registry: Dict[str, float] = {}
        self._dynamic_poll_registry[point_id] = float(cadence_seconds)

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
            self._sim_value_timestamps[point_config.point_id] = time.time()
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
            timestamp=datetime.now(timezone.utc),
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
                _now = time.time()
                for k in self._sim_values:
                    drift = random.uniform(-0.5, 0.5)
                    self._sim_values[k] = max(0, self._sim_values[k] + drift)
                    self._sim_value_timestamps[k] = _now

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
