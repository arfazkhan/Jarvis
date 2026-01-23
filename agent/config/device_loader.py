"""
ARVIS Device Configuration Loader
----------------------------------
Loads device definitions from config/devices.yaml
Validates config and provides typed access to devices.
"""

import os
import yaml
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DeviceConfig:
    """Represents a single device configuration."""
    device_id: str
    name: str
    type: str  # light, switch, fan, thermostat, sensor, cover
    node_id: int
    endpoint: int
    capabilities: List[str] = field(default_factory=list)
    room: Optional[str] = None
    speed_levels: Optional[int] = None  # For fans
    
    def has_capability(self, cap: str) -> bool:
        """Check if device supports a capability."""
        return cap in self.capabilities
    
    def __repr__(self):
        return f"Device({self.device_id}, type={self.type}, node={self.node_id}, ep={self.endpoint})"


@dataclass 
class DeviceGroup:
    """Represents a group of devices."""
    name: str
    device_ids: List[str]


class DeviceLoader:
    """
    Loads and validates device configuration from YAML.
    
    Usage:
        loader = DeviceLoader("config/devices.yaml")
        devices = loader.get_all_devices()
        light = loader.get_device("living_room_light")
    """
    
    VALID_TYPES = {"light", "switch", "fan", "thermostat", "sensor", "cover"}
    VALID_CAPABILITIES = {"on_off", "brightness", "color_temp", "color", "speed", "temperature", "position"}
    
    def __init__(self, config_path: str = "config/devices.yaml"):
        self.config_path = Path(config_path)
        self.devices: Dict[str, DeviceConfig] = {}
        self.groups: Dict[str, DeviceGroup] = {}
        self.rooms: List[str] = []
        self._raw_config: Dict[str, Any] = {}
        
        self._load()
    
    def _load(self):
        """Load and parse the YAML config file."""
        if not self.config_path.exists():
            print(f"[DeviceLoader] Warning: {self.config_path} not found, using empty config")
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"[DeviceLoader] Error parsing YAML: {e}")
            return
        
        # Parse devices
        raw_devices = self._raw_config.get("devices", {})
        for device_id, device_data in raw_devices.items():
            if not self._validate_device(device_id, device_data):
                continue
            
            self.devices[device_id] = DeviceConfig(
                device_id=device_id,
                name=device_data.get("name", device_id),
                type=device_data.get("type", "switch"),
                node_id=device_data.get("node_id", 1),
                endpoint=device_data.get("endpoint", 1),
                capabilities=device_data.get("capabilities", ["on_off"]),
                room=device_data.get("room"),
                speed_levels=device_data.get("speed_levels")
            )
        
        # Parse groups
        raw_groups = self._raw_config.get("groups", {})
        for group_name, device_ids in raw_groups.items():
            self.groups[group_name] = DeviceGroup(name=group_name, device_ids=device_ids)
        
        # Parse rooms
        self.rooms = self._raw_config.get("rooms", [])
        
        print(f"[DeviceLoader] Loaded {len(self.devices)} devices, {len(self.groups)} groups, {len(self.rooms)} rooms")
    
    def _validate_device(self, device_id: str, data: dict) -> bool:
        """Validate a device configuration."""
        if not isinstance(data, dict):
            print(f"[DeviceLoader] Warning: Invalid device format for {device_id}")
            return False
        
        device_type = data.get("type", "switch")
        if device_type not in self.VALID_TYPES:
            print(f"[DeviceLoader] Warning: Unknown device type '{device_type}' for {device_id}")
        
        capabilities = data.get("capabilities", [])
        for cap in capabilities:
            if cap not in self.VALID_CAPABILITIES:
                print(f"[DeviceLoader] Warning: Unknown capability '{cap}' for {device_id}")
        
        # Required fields
        if "node_id" not in data:
            print(f"[DeviceLoader] Warning: Missing node_id for {device_id}, using default 1")
        if "endpoint" not in data:
            print(f"[DeviceLoader] Warning: Missing endpoint for {device_id}, using default 1")
        
        return True
    
    def get_device(self, device_id: str) -> Optional[DeviceConfig]:
        """Get a device by ID."""
        return self.devices.get(device_id)
    
    def get_all_devices(self) -> Dict[str, DeviceConfig]:
        """Get all loaded devices."""
        return self.devices
    
    def get_devices_by_type(self, device_type: str) -> List[DeviceConfig]:
        """Get all devices of a specific type."""
        return [d for d in self.devices.values() if d.type == device_type]
    
    def get_devices_by_room(self, room: str) -> List[DeviceConfig]:
        """Get all devices in a specific room."""
        return [d for d in self.devices.values() if d.room == room]
    
    def get_devices_in_group(self, group_name: str) -> List[DeviceConfig]:
        """Get all devices in a group."""
        group = self.groups.get(group_name)
        if not group:
            return []
        return [self.devices[did] for did in group.device_ids if did in self.devices]
    
    def resolve_device_reference(self, reference: str) -> List[DeviceConfig]:
        """
        Resolve a device reference to actual devices.
        
        Supports:
          - Device ID: "living_room_light"
          - Group: "all_lights"
          - Room: "living_room" (returns all devices in room)
          - Type: "lights" (returns all lights)
        """
        # Try exact device match
        if reference in self.devices:
            return [self.devices[reference]]
        
        # Try group match
        if reference in self.groups:
            return self.get_devices_in_group(reference)
        
        # Try room match
        if reference in self.rooms:
            return self.get_devices_by_room(reference)
        
        # Try type match (plural/singular)
        type_map = {
            "lights": "light", "light": "light",
            "switches": "switch", "switch": "switch",
            "fans": "fan", "fan": "fan"
        }
        if reference.lower() in type_map:
            return self.get_devices_by_type(type_map[reference.lower()])
        
        # Fuzzy match by name
        reference_lower = reference.lower()
        matches = [d for d in self.devices.values() if reference_lower in d.name.lower()]
        if matches:
            return matches
        
        return []
    
    def get_device_for_matter(self, device_id: str) -> Optional[dict]:
        """Get Matter-specific info for a device (node_id, endpoint)."""
        device = self.get_device(device_id)
        if not device:
            return None
        return {
            "node_id": device.node_id,
            "endpoint": device.endpoint,
            "type": device.type,
            "capabilities": device.capabilities
        }
    
    def to_llm_context(self) -> str:
        """Generate device summary for LLM context."""
        lines = ["Available devices:"]
        for device in self.devices.values():
            caps = ", ".join(device.capabilities)
            lines.append(f"  - {device.device_id} ({device.name}): {device.type} [{caps}]")
        
        if self.groups:
            lines.append("\nDevice groups:")
            for group_name, group in self.groups.items():
                lines.append(f"  - {group_name}: {', '.join(group.device_ids)}")
        
        return "\n".join(lines)


# Singleton instance for easy import
_loader: Optional[DeviceLoader] = None

def get_device_loader(config_path: str = "config/devices.yaml") -> DeviceLoader:
    """Get or create the device loader singleton."""
    global _loader
    if _loader is None:
        _loader = DeviceLoader(config_path)
    return _loader


def reload_devices(config_path: str = "config/devices.yaml") -> DeviceLoader:
    """Force reload device configuration."""
    global _loader
    _loader = DeviceLoader(config_path)
    return _loader
