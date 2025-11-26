"""
Sensor Registry
---------------
Single source of truth for all sensors.
Loads configuration from sensors.yaml.
"""

import yaml
import os
from typing import List, Optional, Dict
from agent_sensors.sensor_models import Sensor

class SensorRegistry:
    def __init__(self, config_path: str = "agent_sensors/config/sensors.yaml"):
        self.config_path = config_path
        self._sensors: Dict[str, Sensor] = {}
        self._load_sensors()

    def _load_sensors(self):
        """Load sensors from YAML config"""
        if not os.path.exists(self.config_path):
            print(f"Warning: Sensor config not found at {self.config_path}")
            return

        with open(self.config_path, "r") as f:
            data = yaml.safe_load(f)
            
        for s_data in data.get("sensors", []):
            sensor = Sensor(
                id=s_data["id"],
                type=s_data["type"],
                room=s_data.get("room"),
                meta=s_data.get("meta", {})
            )
            self._sensors[sensor.id] = sensor

    def get_sensor(self, sensor_id: str) -> Optional[Sensor]:
        """Get sensor by ID"""
        return self._sensors.get(sensor_id)

    def get_sensors_by_room(self, room: str) -> List[Sensor]:
        """Get all sensors in a specific room"""
        return [s for s in self._sensors.values() if s.room == room]

    def get_sensors_by_type(self, sensor_type: str) -> List[Sensor]:
        """Get all sensors of a specific type"""
        return [s for s in self._sensors.values() if s.type == sensor_type]

    def all_sensors(self) -> List[Sensor]:
        """Get all registered sensors"""
        return list(self._sensors.values())
