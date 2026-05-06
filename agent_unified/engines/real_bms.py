"""
Real BMS Engine — wraps BACnet adapter for ARVIS BMS tools.
"""

import asyncio
import logging
import yaml
from typing import List, Dict, Any, Optional

from agent_commercial.bacnet_adapter import (
    BACnetAdapter,
    BACnetSimulatorAdapter,
    BACnetPoint,
)
from agent_commercial.bms_data_model import BMSDataPoint

logger = logging.getLogger("arvis.engines.real_bms")


class RealBMS:
    """
    Production-ready BMS engine for ARVIS.

    Supports two modes:
    - mode='bacnet':   Real BACnet/IP via bacpypes3 (async-native).
                        Connect to real devices on the LAN.
    - mode='simulator': In-process simulator — no hardware needed.
                        Uses realistic value drift for demo/testing.

    This is the standard interface used by all BMS tools.
    """

    def __init__(
        self,
        config: Dict[str, Any] = None,
        mode: str = "simulator",
        bacnet_port: int = 47808,
        local_address: str = "0.0.0.0",
    ):
        self.mode = mode
        self._config = config or {}
        self._value_cache: Dict[str, float] = {}
        self._active_alarms: List[Dict] = []
        self._adapter = None
        self._poll_task: Optional[asyncio.Task] = None

        if mode == "simulator":
            self._adapter = BACnetSimulatorAdapter()
        else:
            self._adapter = BACnetAdapter(
                local_address=local_address,
                port=bacnet_port,
                device_id=999,
            )

        # Register cache callback
        self._adapter.on_point_update(self.update_cache)

        # Parse equipment from config
        self._equipment_registry: Dict[str, Dict] = {}
        if config:
            self._parse_equipment_from_config(config)

    def _parse_equipment_from_config(self, config: Dict[str, Any]) -> None:
        """Build equipment registry from bms_config.yaml sections."""
        points = config.get("bacnet", {}).get("points", [])
        for p in points:
            eq_id = p.get("equipment_id", "")
            if eq_id and eq_id not in self._equipment_registry:
                if "CH" in eq_id:
                    eq_type, name = "chiller", f"Chiller {eq_id.split('-')[-1]}"
                elif "AHU" in eq_id:
                    eq_type, name = "ahu", f"AHU {eq_id.split('-')[-1]}"
                elif "METER" in eq_id:
                    eq_type, name = "meter", f"Energy Meter {eq_id.split('-')[-1]}"
                else:
                    eq_type, name = "unknown", eq_id

                self._equipment_registry[eq_id] = {
                    "id": eq_id,
                    "name": name,
                    "type": eq_type,
                    "status": "running",
                    "location": "Mechanical Room",
                }

    # ─── Connection ───────────────────────────────────────────

    async def connect(self) -> bool:
        """Connect adapter and start polling."""
        if self.mode == "simulator":
            connected = await self._adapter.connect()
        else:
            connected = await self._adapter.connect()
            if connected:
                await self._adapter.discover_devices(timeout_seconds=5)

        if connected:
            if self._config:
                self._adapter.load_points_from_config(self._config.get("bacnet", {}))
            await self._adapter.start_polling(interval_seconds=10)

        logger.info(f"RealBMS [{self.mode}] connected={connected}")
        return connected

    async def disconnect(self) -> None:
        await self._adapter.stop_polling()
        await self._adapter.disconnect()

    # ─── Cache ───────────────────────────────────────────────

    def update_cache(self, point: BMSDataPoint) -> None:
        """Callback: update internal cache on each point read."""
        self._value_cache[point.point_id] = point.value

    # ─── Standard BMS Interface ──────────────────────────────

    def get_equipment(self, eq_id: str):
        data = self._equipment_registry.get(eq_id)
        if not data:
            return None

        class EqObj:
            pass

        obj = EqObj()
        obj.equipment_id = data["id"]
        obj.name = data["name"]
        obj.eq_type = data["type"]
        obj.status = data["status"]
        obj.location = data["location"]
        return obj

    def get_points_by_equipment(self, eq_id: str) -> List[Any]:
        points = []
        for pid, val in self._value_cache.items():
            if pid.startswith(eq_id + "/") or pid.startswith(eq_id + "-"):
                class Pt:
                    pass

                obj = Pt()
                obj.point_id = pid
                obj.value = val
                obj.name = pid.split("/")[-1].replace("-", " ")
                obj.unit = "°C" if any(
                    x in pid for x in ["TEMP", "SAT", "RAT", "CHWST", "CHWRT"]
                ) else "kW" if "KW" in pid else "%"
                points.append(obj)
        return points

    def get_all_equipment(self) -> List[Any]:
        result = []
        for data in self._equipment_registry.values():
            class Eq:
                pass

            obj = Eq()
            obj.equipment_id = data["id"]
            obj.eq_type = data["type"]
            obj.status = data["status"]
            result.append(obj)
        return result

    def get_active_alarms(self, priority_filter: str = None) -> List[Any]:
        result = []
        for a in self._active_alarms:
            if priority_filter and priority_filter.lower() not in (
                a.get("priority", "low") or ""
            ).lower():
                continue

            class Alm:
                pass

            obj = Alm()
            obj.to_dict = lambda x=a: x
            result.append(obj)
        return result
