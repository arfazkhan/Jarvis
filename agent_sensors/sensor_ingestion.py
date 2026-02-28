"""
Sensor Ingestion
----------------
Ingests raw sensor events, validates them, and publishes normalized events.
"""

import time
from typing import Dict, Any, Optional
from arvis_core.event_bus.event_bus import EventBus
from agent_sensors.sensor_models import SensorEvent
from agent_sensors.sensor_registry import SensorRegistry

class SensorIngestion:
    def __init__(self, event_bus: EventBus, registry: SensorRegistry):
        self.event_bus = event_bus
        self.registry = registry

    def ingest_event(self, raw_event: Dict[str, Any]):
        """
        Ingest a raw event from API or hardware.
        raw_event: {sensor_id, value, ts?}
        """
        sensor_id = raw_event.get("sensor_id")
        value = raw_event.get("value")
        ts = raw_event.get("ts", time.time())
        
        # 1. Validate Sensor ID
        sensor = self.registry.get_sensor(sensor_id)
        if not sensor:
            print(f"[SensorIngestion] Warning: Unknown sensor_id {sensor_id}")
            return

        # 2. Normalize
        # (Here we could add type validation based on sensor.type)
        
        event = SensorEvent(
            sensor_id=sensor.id,
            sensor_type=sensor.type,
            room=sensor.room,
            value=value,
            ts=ts,
            source="physical"
        )

        # 3. Publish
        self.event_bus.publish({
            "type": "sensor_event",
            "source": "sensor_ingestion",
            "payload": event.as_dict()
        })
