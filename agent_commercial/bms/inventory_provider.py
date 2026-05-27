"""Point inventory provider — abstracts BACnet point discovery for sim and production.

This module provides a uniform abstraction over "which BACnet points exist in the
field network" so ARVIS tools can answer operator questions of the form:
  - "What points do you see for CH-02?"
  - "Why don't you have a filter DP reading?"
  - "Which equipment is unmapped?"

Two providers are shipped:
  * SimPointInventoryProvider — reads from the in-process BACnetSimulatorAdapter
    used by scratch/marina_prove_it.py (points live in `adapter._points` as
    BACnetPoint dataclasses, latest values in `adapter._sim_values`).
  * BACnetPointInventoryProvider — production stub. Raises NotImplementedError
    until wired against live BACnet/IP via bacpypes3.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class DeviceInfo:
    device_id: str           # e.g. "CH-02"
    device_type: str         # e.g. "chiller", "ahu"
    bacnet_address: Optional[str] = None  # e.g. "260001"
    vendor: Optional[str] = None          # e.g. "Carrier"
    model: Optional[str] = None           # e.g. "30XA"


@dataclass
class PointMeta:
    point_id: str            # canonical id, e.g. "CH-02/CHWST"
    point_name: str          # short name, e.g. "CHWST"
    device_id: str           # parent equipment
    bacnet_object_type: Optional[str] = None       # e.g. "analogInput"
    bacnet_object_instance: Optional[int] = None   # e.g. 4097
    unit: Optional[str] = None
    description: Optional[str] = None
    is_polled_by_arvis: bool = False   # set by tool handler via cross-ref
    last_value: Optional[float] = None
    last_update_epoch: Optional[float] = None
    age_seconds: Optional[float] = None  # computed at read time
    status: str = "unknown"  # "fresh" | "stale" | "unmapped" | "no_data"


class PointInventoryProvider(ABC):
    """Abstract provider. Sim reads from BACnetSimulatorAdapter. Prod reads from
    real BACnet/IP via bacpypes3."""

    @abstractmethod
    async def list_devices(self) -> List[DeviceInfo]:
        ...

    @abstractmethod
    async def list_points(self, device_filter: Optional[str] = None) -> List[PointMeta]:
        """Return ALL points known to the BACnet layer, regardless of ARVIS poll scope."""
        ...

    @abstractmethod
    async def get_point_freshness(self, point_id: str) -> Optional[float]:
        """Return age_seconds for a point's last update, or None if never updated."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


# --- Sim implementation ---------------------------------------------------

class SimPointInventoryProvider(PointInventoryProvider):
    """Reads from the in-process BACnetSimulatorAdapter registry.

    The adapter (agent_commercial.bacnet_adapter.BACnetSimulatorAdapter) stores:
      - self._points: Dict[str, BACnetPoint]  — point metadata
      - self._sim_values: Dict[str, float]    — latest sim values
    The adapter does NOT track per-point timestamps, so age_seconds is reported
    as None (status='fresh' if a value exists, 'no_data' if not).
    """

    def __init__(self, bacnet_sim):
        self._sim = bacnet_sim

    def provider_name(self) -> str:
        return "sim"

    def _iter_points(self):
        """Yield (point_id, BACnetPoint) tuples from the adapter."""
        points_attr = getattr(self._sim, "_points", None)
        if isinstance(points_attr, dict):
            for pid, pdata in points_attr.items():
                yield pid, pdata

    async def list_devices(self) -> List[DeviceInfo]:
        devices: Dict[str, DeviceInfo] = {}
        for _, pdata in self._iter_points():
            eq_id = getattr(pdata, "equipment_id", None) or "unknown"
            if eq_id not in devices:
                bacnet_dev = getattr(pdata, "device_id", None)
                devices[eq_id] = DeviceInfo(
                    device_id=eq_id,
                    device_type=self._infer_device_type(eq_id),
                    bacnet_address=str(bacnet_dev) if bacnet_dev is not None else None,
                )
        return list(devices.values())

    async def list_points(self, device_filter: Optional[str] = None) -> List[PointMeta]:
        out: List[PointMeta] = []
        sim_values = getattr(self._sim, "_sim_values", {}) or {}
        for pid, pdata in self._iter_points():
            eq_id = getattr(pdata, "equipment_id", None) or (pid.split("/")[0] if "/" in pid else "unknown")
            if device_filter and device_filter not in eq_id:
                continue

            last_value = sim_values.get(pid)
            last_epoch = self._sim.get_point_last_update_epoch(pid) if hasattr(self._sim, "get_point_last_update_epoch") else None
            age_seconds = (time.time() - last_epoch) if last_epoch is not None else None
            if age_seconds is None:
                status = "no_data" if last_value is None else "fresh"
            elif age_seconds > 300:
                status = "stale"
            else:
                status = "fresh"

            point_name = getattr(pdata, "point_name", None) or (pid.split("/")[-1] if "/" in pid else pid)

            out.append(PointMeta(
                point_id=pid,
                point_name=point_name,
                device_id=eq_id,
                bacnet_object_type=getattr(pdata, "object_type", None),
                bacnet_object_instance=getattr(pdata, "object_instance", None),
                unit=getattr(pdata, "unit", None) or None,
                description=None,
                last_value=float(last_value) if isinstance(last_value, (int, float)) else None,
                last_update_epoch=last_epoch,
                age_seconds=age_seconds,
                status=status,
            ))
        return out

    async def get_point_freshness(self, point_id: str) -> Optional[float]:
        last_epoch = self._sim.get_point_last_update_epoch(point_id) if hasattr(self._sim, "get_point_last_update_epoch") else None
        if last_epoch is None:
            return None
        return time.time() - last_epoch

    @staticmethod
    def _infer_device_type(device_id: str) -> str:
        if device_id.startswith("CH-"):
            return "chiller"
        if device_id.startswith("AHU-"):
            return "ahu"
        if device_id.startswith("CT-"):
            return "cooling_tower"
        if device_id.startswith("VAV-"):
            return "vav"
        if device_id.startswith("FCU-"):
            return "fcu"
        if device_id.startswith("ELEV-"):
            return "elevator"
        if device_id.startswith("FLR-"):
            return "floor"
        if device_id.startswith("PUMP-"):
            return "pump"
        if device_id.startswith("METER-") or "METER" in device_id.upper():
            return "meter"
        return "unknown"


# --- Production stub ------------------------------------------------------

class BACnetPointInventoryProvider(PointInventoryProvider):
    """Production implementation. Reads from live BACnet/IP via bacpypes3.

    NOT IMPLEMENTED — placeholder so production code path exists.

    Contract for future implementation:
    - Use bacpypes3.Application + Who-Is discovery to enumerate devices
    - For each device, ReadPropertyMultiple of objectList (chunked at 100)
    - For each object, read present-value, object-name, units, status-flags, reliability
    - Cache inventory for 1 hour (BACnet enumeration is slow on 12k+ points)
    - Handle COV subscriptions for freshness tracking
    - Respect device passwords / segment auth from secrets layer
    - Graceful degradation on segment timeout (return partial enumeration)

    Config required at construction:
    - bacnet_local_address: str  (e.g. "192.168.1.100/24")
    - bacnet_device_id: int      (this controller's id)
    - discovery_timeout_s: int = 30
    - segment_chunk_size: int = 100
    - cache_ttl_s: int = 3600
    """

    def __init__(self, config: dict):
        self._config = config
        raise NotImplementedError(
            "BACnetPointInventoryProvider is a production stub. "
            "Implement using bacpypes3 Who-Is + ReadPropertyMultiple. "
            "See class docstring for contract."
        )

    def provider_name(self) -> str:
        return "production"

    async def list_devices(self) -> List[DeviceInfo]:
        raise NotImplementedError

    async def list_points(self, device_filter: Optional[str] = None) -> List[PointMeta]:
        raise NotImplementedError

    async def get_point_freshness(self, point_id: str) -> Optional[float]:
        raise NotImplementedError


# --- Factory --------------------------------------------------------------

_active_provider: Optional[PointInventoryProvider] = None


def init_provider(mode: str = "sim", **kwargs) -> PointInventoryProvider:
    """Boot-time provider selection. mode = 'sim' | 'production'."""
    global _active_provider
    if mode == "sim":
        bacnet_sim = kwargs.get("bacnet_sim")
        if bacnet_sim is None:
            raise ValueError("sim mode requires bacnet_sim kwarg")
        _active_provider = SimPointInventoryProvider(bacnet_sim)
    elif mode == "production":
        _active_provider = BACnetPointInventoryProvider(kwargs.get("config", {}))
    else:
        raise ValueError(f"unknown mode: {mode}")
    return _active_provider


def get_provider() -> PointInventoryProvider:
    if _active_provider is None:
        raise RuntimeError("PointInventoryProvider not initialized. Call init_provider() at boot.")
    return _active_provider
