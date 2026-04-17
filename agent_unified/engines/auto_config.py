"""
ARVIS BMS Auto-Configurator
==========================

LLM-driven automatic BMS discovery, point mapping, and config generation.
Eliminates the manual YAML editing step.

Workflow:
  1. Connect to BACnet network
  2. Discover all devices via Who-Is
  3. For each device, read all object summaries
  4. Ask LLM to infer equipment type + point semantics
  5. Generate config/bms_config.yaml + equipment topology

Usage:
    configurator = AutoConfigurator()
    await configurator.run()        # Full auto-run
    await configurator.step1_discover()
    await configurator.step2_read_objects()
    await configurator.step3_infer()
    await configurator.step4_write()
"""

import asyncio
import logging
import json
import yaml
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from agent_unified.schema.bms import BMSDataPoint

logger = logging.getLogger("arvis.bms.autoconfig")

# ─── BACnet Protocol Constants ─────────────────────────────────────────────

BACNET_OBJECT_TYPES = [
    "analogInput", "analogOutput", "analogValue",
    "binaryInput", "binaryOutput", "binaryValue",
    "multiStateInput", "multiStateOutput", "multiStateValue",
    "device",
]

BACNET_PRESENCE_OBJECTS = [
    ("analogInput", 0, "SupplyAirTemp"),
    ("analogInput", 1, "ReturnAirTemp"),
    ("analogInput", 2, "OutdoorAirTemp"),
    ("analogInput", 3, "MixedAirTemp"),
    ("analogInput", 4, "CoolingCoilValve"),
    ("analogInput", 5, "HeatingCoilValve"),
    ("analogInput", 6, "FanStatus"),
    ("analogInput", 7, "FilterDifferentialPressure"),
    ("binaryInput", 0, "RunStatus"),
    ("binaryInput", 1, "AlarmStatus"),
]

EQUIPMENT_SIGNATURE_PATTERNS = {
    "AHU": {
        "keywords": ["supply", "return", "outdoor", "mixed", "air", "fan", "filter", "duct", "ahu", "vav"],
        "required_points": ["temperature", "fan"],
        "parent_type": None,
    },
    "CHILLER": {
        "keywords": ["chilled", "chw", "condenser", "cooling", "chiller", "compressor", "refrigerant"],
        "required_points": ["temperature", "power", "load"],
        "parent_type": None,
    },
    "BOILER": {
        "keywords": ["hot", "heating", "boiler", "hwst", "hwrt", "combustion", "gas"],
        "required_points": ["temperature", "fire", "gas"],
        "parent_type": None,
    },
    "COOLING_TOWER": {
        "keywords": ["tower", "wetbulb", "basin", "fan", "cell"],
        "required_points": ["temperature", "fan"],
        "parent_type": "CHILLER",
    },
    "FCU": {
        "keywords": ["unit", "zone", "fcu", "fan-coil", "thermostat"],
        "required_points": ["temperature"],
        "parent_type": "AHU",
    },
    "VAV": {
        "keywords": ["vav", "variable", "box", "zone", "damper", "reheat"],
        "required_points": ["temperature", "damper"],
        "parent_type": "AHU",
    },
    "PUMP": {
        "keywords": ["pump", "circulator", "primary", "secondary"],
        "required_points": ["status", "speed"],
        "parent_type": None,
    },
    "METER": {
        "keywords": ["meter", "kwh", "kw", "power", "energy", "demand", "utility"],
        "required_points": ["power"],
        "parent_type": None,
    },
}


# ─── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class DiscoveredDevice:
    device_id: int
    device_name: str
    address: str
    vendor_name: str = ""
    model_name: str = ""
    object_count: int = 0
    objects: Dict[str, List] = field(default_factory=dict)  # obj_type -> list of instance IDs


@dataclass
class InferredPoint:
    point_id: str
    name: str
    object_type: str
    object_instance: int
    equipment_id: str
    equipment_type: str
    unit: str
    inferred_semantic: str  # e.g. "supply_air_temp", "chilled_water_return_temp"
    confidence: float


@dataclass
class InferredEquipment:
    equipment_id: str
    name: str
    eq_type: str
    location: str
    parent_id: str
    children: List[str]
    points: List[InferredPoint]
    device_id: int
    confidence: float


# ─── Main Configurator ──────────────────────────────────────────────────────

class AutoConfigurator:
    """
    LLM-powered BMS auto-discovery and config generator.

    Step 1: Discover BACnet devices (Who-Is)
    Step 2: Read all object instances per device
    Step 3: LLM inference — map raw objects → equipment + points
    Step 4: Generate bms_config.yaml + devices.yaml
    """

    def __init__(
        self,
        bacnet_adapter,  # BACnetAdapter instance (or BACnetSimulatorAdapter)
        llm,              # UnifiedLLM instance
        output_dir: str = "config",
        building_id: str = "AUTO-DISCOVERED",
    ):
        self.adapter = bacnet_adapter
        self.llm = llm
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.building_id = building_id
        self.discovered_devices: List[DiscoveredDevice] = []
        self.inferred_equipment: List[InferredEquipment] = []
        self.inferred_points: List[InferredPoint] = []

    # ─── Step 1: Device Discovery ──────────────────────────────────────────

    async def step1_discover(self, timeout: int = 30) -> List[DiscoveredDevice]:
        """Discover all BACnet devices on the network."""
        logger.info(f"[AutoConfig] Step 1: Discovering devices (timeout={timeout}s)...")

        connected = await self.adapter.connect()
        if not connected:
            raise RuntimeError("Failed to connect to BACnet network. Is BAC0 installed?")

        devices = await self.adapter.discover_devices(timeout_seconds=timeout)
        self.discovered_devices = []

        for dev in devices:
            d = DiscoveredDevice(
                device_id=dev.device_id,
                device_name=dev.device_name,
                address=dev.address,
                vendor_name=getattr(dev, "vendor_name", ""),
                model_name=getattr(dev, "model_name", ""),
                object_count=0,
            )
            self.discovered_devices.append(d)

        logger.info(f"[AutoConfig] Found {len(self.discovered_devices)} devices")
        return self.discovered_devices

    # ─── Step 2: Read All Objects ─────────────────────────────────────────

    async def step2_read_objects(self) -> None:
        """For each device, enumerate all BACnet object instances."""
        logger.info("[AutoConfig] Step 2: Reading object inventories...")

        for device in self.discovered_devices:
            device.objects = {}
            device.object_count = 0

            for obj_type in BACNET_OBJECT_TYPES:
                instance_ids = []

                # Try to read a range of instances (0-200) to find present objects
                # Real BACnet devices expose ~10-200 objects; we scan systematically
                for instance in range(0, 200):
                    try:
                        value = await self.adapter.read_property(
                            device_address=device.address,
                            object_type=obj_type,
                            object_instance=instance,
                            property_name="presentValue",
                        )
                        if value is not None:
                            instance_ids.append(instance)
                            device.object_count += 1
                    except Exception:
                        break  # No more objects of this type

                if instance_ids:
                    device.objects[obj_type] = instance_ids
                    logger.debug(
                        f"  {device.device_name}: {obj_type} instances {instance_ids}"
                    )

        # Save raw discovery
        self._save_discovery_report()
        logger.info("[AutoConfig] Object enumeration complete")

    # ─── Step 3: LLM Inference ────────────────────────────────────────────

    async def step3_infer(self) -> None:
        """Use LLM to infer equipment types, names, and point semantics."""
        logger.info("[AutoConfig] Step 3: LLM inference...")

        prompt = self._build_inference_prompt()
        response = await self.llm.ask(prompt)

        try:
            parsed = json.loads(response.content)
            self._parse_llm_inference(parsed)
        except json.JSONDecodeError:
            logger.warning("[AutoConfig] LLM didn't return clean JSON, using fallback parser")
            self._fallback_parse(response.content)

        logger.info(
            f"[AutoConfig] Inferred {len(self.inferred_equipment)} equipment, "
            f"{len(self.inferred_points)} points"
        )

    def _build_inference_prompt(self) -> str:
        devices_summary = []
        for d in self.discovered_devices:
            obj_lines = []
            for obj_type, instances in d.objects.items():
                for inst in instances:
                    obj_lines.append(f"  - {obj_type}:{inst}")
            devices_summary.append(
                f"Device: {d.device_name} (ID={d.device_id}, Vendor={d.vendor_name}, "
                f"Model={d.model_name})\nObjects:\n" + "\n".join(obj_lines)
            )

        prompt = f"""You are a BMS commissioning engineer. Given raw BACnet device data, produce a complete equipment and point mapping.

Buildings: {self.building_id}

Devices discovered:
{chr(10).join(devices_summary)}

For each device, infer:
1. Equipment type (AHU, CHILLER, BOILER, FCU, VAV, PUMP, METER, CT, OTHER)
2. Equipment ID (e.g., "AHU-01", "CH-01")
3. Equipment name
4. Parent equipment ID (if child, e.g., VAV belongs to AHU)
5. For each BACnet object, infer:
   - Semantic name (e.g., "Supply Air Temperature", "Chilled Water Return Temp")
   - Engineering unit (°C, %, kW, Pa, etc.)
   - ARVIS point_id (e.g., "AHU-01/SAT")
   - Equipment it belongs to

Output ONLY valid JSON with this schema:
{{
  "equipment": [
    {{
      "equipment_id": "AHU-01",
      "name": "Air Handler Unit 1",
      "eq_type": "AHU",
      "location": "Floor 1",
      "parent_id": "",
      "children": [],
      "device_id": 2001,
      "confidence": 0.9
    }}
  ],
  "points": [
    {{
      "point_id": "AHU-01/SAT",
      "name": "Supply Air Temperature",
      "object_type": "analogInput",
      "object_instance": 1,
      "equipment_id": "AHU-01",
      "equipment_type": "AHU",
      "unit": "°C",
      "inferred_semantic": "supply_air_temp",
      "confidence": 0.95
    }}
  ]
}}

Rules:
- Infer units from point name: temperature→°C, pressure→Pa, speed→%, power→kW
- AHUs always have: SAT (supply air temp), RAT (return air temp), fan speed/damper
- Chillers always have: CHWST, CHWRT (chilled water supply/return temp), power, load
- Assign equipment IDs sequentially: AHU-01, AHU-02, CH-01, CH-02, METER-01
- If a VAV/FCU references an AHU as parent, add that AHU to children
- Meters (kWh, kW) have no parent
"""
        return prompt

    def _parse_llm_inference(self, parsed: dict) -> None:
        for eq in parsed.get("equipment", []):
            self.inferred_equipment.append(InferredEquipment(
                equipment_id=eq["equipment_id"],
                name=eq["name"],
                eq_type=eq["eq_type"],
                location=eq.get("location", ""),
                parent_id=eq.get("parent_id", ""),
                children=eq.get("children", []),
                device_id=eq["device_id"],
                confidence=eq.get("confidence", 0.5),
            ))

        for pt in parsed.get("points", []):
            self.inferred_points.append(InferredPoint(
                point_id=pt["point_id"],
                name=pt["name"],
                object_type=pt["object_type"],
                object_instance=pt["object_instance"],
                equipment_id=pt["equipment_id"],
                equipment_type=pt["equipment_type"],
                unit=pt.get("unit", ""),
                inferred_semantic=pt.get("inferred_semantic", ""),
                confidence=pt.get("confidence", 0.5),
            ))

    def _fallback_parse(self, raw: str) -> None:
        """Fallback: heuristic parse when LLM doesn't return clean JSON."""
        import re
        # Extract JSON block if LLM wrapped it in markdown
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            logger.error("[AutoConfig] Cannot parse LLM response at all")
            return
        try:
            parsed = json.loads(match.group())
            self._parse_llm_inference(parsed)
        except Exception as e:
            logger.error(f"[AutoConfig] Fallback parse failed: {e}")

    # ─── Step 4: Write Config Files ────────────────────────────────────────

    def step4_write(self) -> Path:
        """Generate bms_config.yaml and return the path."""
        logger.info("[AutoConfig] Step 4: Writing config files...")

        config = {
            "_generated": datetime.now().isoformat(),
            "_source": "auto_configurator",
            "bacnet": {
                "enabled": True,
                "local_address": "0.0.0.0",
                "port": 47809,
                "discovery_timeout": 30,
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.device_name,
                        "address": d.address,
                        "poll_interval": 30,
                    }
                    for d in self.discovered_devices
                ],
            },
            "points": [
                {
                    "point_id": pt.point_id,
                    "device_id": self._device_id_for_equipment(pt.equipment_id),
                    "object_type": pt.object_type,
                    "object_instance": pt.object_instance,
                    "name": pt.name,
                    "equipment_id": pt.equipment_id,
                    "unit": pt.unit,
                }
                for pt in self.inferred_points
            ],
            "equipment": self._build_equipment_topology(),
            "gsas": {
                "enabled": True,
                "building_id": self.building_id,
                "target_rating": 3,
            },
        }

        out_path = self.output_dir / "bms_config.yaml"
        with open(out_path, "w") as f:
            yaml.dump(config, f, sort_keys=False, default_flow_style=False)

        logger.info(f"[AutoConfig] Written: {out_path}")
        return out_path

    def _device_id_for_equipment(self, equipment_id: str) -> int:
        for eq in self.inferred_equipment:
            if eq.equipment_id == equipment_id:
                return eq.device_id
        return 999

    def _build_equipment_topology(self) -> Dict:
        """Build equipment section for bms_config.yaml."""
        by_type = {}
        for eq in self.inferred_equipment:
            if eq.eq_type not in by_type:
                by_type[eq.eq_type] = []
            by_type[eq.eq_type].append({
                "equipment_id": eq.equipment_id,
                "name": eq.name,
                "location": eq.location,
                "parent": eq.parent_id,
                "children": eq.children,
            })

        # Build nested dict by type
        result = {}
        type_map = {
            "CHILLER": "chillers",
            "AHU": "ahus",
            "FCU": "fcus",
            "VAV": "vavs",
            "BOILER": "boilers",
            "PUMP": "pumps",
            "METER": "meters",
            "CT": "cooling_towers",
        }
        for eq_type, key in type_map.items():
            if key in by_type:
                result[key] = by_type[key]

        # Fallback: put unknown types under "other"
        return result

    # ─── Full Auto-Run ────────────────────────────────────────────────────

    async def run(self) -> Path:
        """Run all 4 steps automatically."""
        await self.step1_discover()
        await self.step2_read_objects()
        await self.step3_infer()
        return self.step4_write()

    # ─── Reporting ───────────────────────────────────────────────────────

    def _save_discovery_report(self) -> None:
        """Save raw discovery data for debugging/audit."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "building_id": self.building_id,
            "devices": [
                {
                    "device_id": d.device_id,
                    "device_name": d.device_name,
                    "address": d.address,
                    "vendor_name": d.vendor_name,
                    "model_name": d.model_name,
                    "object_count": d.object_count,
                    "objects": d.objects,
                }
                for d in self.discovered_devices
            ],
        }
        report_path = self.output_dir / "discovery_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"[AutoConfig] Discovery report: {report_path}")

    def get_summary(self) -> Dict[str, Any]:
        return {
            "devices_discovered": len(self.discovered_devices),
            "equipment_inferred": len(self.inferred_equipment),
            "points_inferred": len(self.inferred_points),
            "equipment_types": list(set(e.eq_type for e in self.inferred_equipment)),
        }
