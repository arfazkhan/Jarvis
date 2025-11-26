"""
Occupancy Sensor (Virtual)
--------------------------
Infers room occupancy based on motion and light events.
Heuristics:
- Motion = Occupied (Confidence 1.0)
- Light On = Boost confidence
- No Motion > X min = Decay confidence
"""

import time
from typing import Dict, Optional
from agent_sensors.sensor_models import SensorEvent, RoomOccupancy

class OccupancySensor:
    def __init__(self, timeout_seconds: float = 300.0): # 5 minutes default
        self.timeout_seconds = timeout_seconds
        self.room_states: Dict[str, Dict] = {} # room -> {last_motion: ts, last_light_interaction: ts, is_light_on: bool}

    def update_from_event(self, event: SensorEvent):
        """Update internal state based on sensor event"""
        if not event.room:
            return

        room = event.room
        if room not in self.room_states:
            self.room_states[room] = {"last_motion": 0, "last_light_interaction": 0, "is_light_on": False}
        
        state = self.room_states[room]
        
        if event.sensor_type == "motion":
            if event.value: # Motion Detected
                state["last_motion"] = event.ts
        
        elif event.sensor_type == "light_level" or event.sensor_type == "light_state":
            # Assuming value is brightness (int) or state (bool)
            # Simplified: any interaction updates timestamp
            state["last_light_interaction"] = event.ts
            # If we had state tracking, we'd update is_light_on
            # For now, assume if value > 0 it's on
            if isinstance(event.value, (int, float)) and event.value > 0:
                state["is_light_on"] = True
            elif isinstance(event.value, bool):
                 state["is_light_on"] = event.value

    def get_room_occupancy(self, room: str) -> RoomOccupancy:
        """Calculate occupancy for a room"""
        state = self.room_states.get(room, {"last_motion": 0, "last_light_interaction": 0, "is_light_on": False})
        
        now = time.time()
        time_since_motion = now - state["last_motion"]
        
        is_occupied = False
        confidence = 0.0
        
        # Heuristic 1: Recent Motion
        if time_since_motion < self.timeout_seconds:
            is_occupied = True
            # Decay confidence linearly from 1.0 to 0.5 over the timeout period
            confidence = 1.0 - (0.5 * (time_since_motion / self.timeout_seconds))
        
        # Heuristic 2: Lights On (Boost)
        # If lights are on, we are more confident someone is there, or at least hasn't left for long
        if state["is_light_on"]:
            if is_occupied:
                confidence = min(1.0, confidence + 0.2)
            else:
                # If lights on but no recent motion, maybe reading?
                # Give it a low probability occupancy
                if time_since_motion < self.timeout_seconds * 2:
                    is_occupied = True
                    confidence = 0.3
        
        return RoomOccupancy(
            room=room,
            is_occupied=is_occupied,
            confidence=round(confidence, 2),
            last_change_ts=state["last_motion"] # Simplified
        )
