"""
State Estimator
---------------
Fuses virtual sensor outputs into a live HomeSituation snapshot.
Orchestrates Virtual Sensors.
"""

import time
from typing import Dict, Any
from agent.event_bus.event_bus import EventBus
from agent_sensors.sensor_models import SensorEvent, HomeSituation, HomePresence, RoomOccupancy, SleepState, EmotionalState
from agent_sensors.virtual_sensors.occupancy_sensor import OccupancySensor
from agent_sensors.virtual_sensors.presence_sensor import PresenceSensor
from agent_sensors.virtual_sensors.sleep_sensor import SleepSensor
from agent_sensors.fusion_rules import infer_time_of_day, infer_activity_hint
from agent_sensors.sensor_registry import SensorRegistry

class StateEstimator:
    def __init__(self, event_bus: EventBus, registry: SensorRegistry):
        self.event_bus = event_bus
        self.registry = registry
        
        # Virtual Sensors
        self.occupancy_sensor = OccupancySensor()
        self.presence_sensor = PresenceSensor()
        self.sleep_sensor = SleepSensor()
        
        # State
        self.current_situation: HomeSituation = self._initial_situation()
        self.last_activity_change_ts: float = time.time()
        
        # Subscribe
        self.event_bus.subscribe("sensor_event", self._on_sensor_event)

    def _initial_situation(self) -> HomeSituation:
        return HomeSituation(
            time_of_day=infer_time_of_day(),
            home_presence=HomePresence("unknown", 0.0, []),
            room_occupancy={},
            sleep_state=SleepState("unknown", 0.0, 0),
            activity_hint=None,
            emotional_state=EmotionalState("neutral", 0.1, time.time()),
            updated_ts=time.time()
        )

    def _on_sensor_event(self, event_dict: Dict[str, Any]):
        """Handle incoming sensor events"""
        payload = event_dict.get("payload", {})
        # Convert dict back to SensorEvent (or just use dict if virtual sensors accept it)
        # Virtual sensors expect SensorEvent object
        event = SensorEvent(
            sensor_id=payload.get("sensor_id"),
            sensor_type=payload.get("sensor_type"),
            room=payload.get("room"),
            value=payload.get("value"),
            ts=payload.get("ts", time.time()),
            source=payload.get("source", "physical")
        )
        
        # Update Virtual Sensors
        self.occupancy_sensor.update_from_event(event)
        self.presence_sensor.update_from_event(event)
        self.sleep_sensor.update_from_event(event)
        
        # Recompute Situation
        self._update_situation()

    def _update_situation(self):
        """Recompute HomeSituation and publish update"""
        # 1. Gather Virtual Sensor Outputs
        # We need to know all rooms to query occupancy
        all_rooms = set(s.room for s in self.registry.all_sensors() if s.room and s.room != "none")
        room_occupancy = {r: self.occupancy_sensor.get_room_occupancy(r) for r in all_rooms}
        
        home_presence = self.presence_sensor.get_home_presence()
        
        time_of_day = infer_time_of_day()
        
        # Sleep sensor needs time_of_day
        sleep_state = self.sleep_sensor.calculate_state(time_of_day)
        
        # 2. Fusion
        raw_activity = infer_activity_hint(time_of_day, home_presence, room_occupancy, sleep_state)
        
        # Apply Hysteresis to Activity Hint
        final_activity = raw_activity
        now = time.time()
        
        if self.current_situation.activity_hint == "sleeping":
            if raw_activity != "sleeping":
                # If raw_activity == "snacking" (triggered by kitchen occupancy)
                # Check if kitchen occupancy is "brief"
                if raw_activity == "snacking" and "kitchen" in room_occupancy:
                    kitchen_occ = room_occupancy["kitchen"]
                    diff = now - kitchen_occ.last_change_ts
                    # If occupied for < 60s, ignore
                    if kitchen_occ.is_occupied and (diff < 60):
                         final_activity = "sleeping"
        
        # Update last change ts
        if final_activity != self.current_situation.activity_hint:
            self.last_activity_change_ts = now
            
        # 3. Create Snapshot
        new_situation = HomeSituation(
            time_of_day=time_of_day,
            home_presence=home_presence,
            room_occupancy=room_occupancy,
            sleep_state=sleep_state,
            activity_hint=final_activity,
            emotional_state=EmotionalState("neutral", 0.1, now), # Default neutral for Phase 4
            updated_ts=now
        )
        
        self.current_situation = new_situation
        
        self.event_bus.publish({
            "type": "situation_update",
            "source": "state_estimator",
            "payload": new_situation.to_dict()
        })
        
    def get_current_situation(self) -> HomeSituation:
        return self.current_situation
