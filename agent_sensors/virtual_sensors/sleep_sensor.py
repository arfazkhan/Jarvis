"""
Sleep Sensor (Virtual)
----------------------
Infers Sleep/Awake state.
Heuristics:
- Time of Day (Night) + Bedroom Occupied + No Motion = Sleeping
- Morning + Motion = Awake
"""

import time
from typing import Literal
from agent_sensors.sensor_models import SensorEvent, SleepState

class SleepSensor:
    def __init__(self):
        self.state: Literal["awake", "winding_down", "sleeping", "unknown"] = "awake"
        self.confidence: float = 1.0
        self.last_state_change: float = time.time()
        
        self.bedroom_last_motion: float = 0
        self.bedroom_lights_on: bool = False
        
    def update_from_event(self, event: SensorEvent):
        if event.room == "bedroom":
            if event.sensor_type == "motion" and event.value:
                self.bedroom_last_motion = event.ts
            elif event.sensor_type == "light_level":
                self.bedroom_lights_on = event.value > 0

    def calculate_state(self, time_of_day: str) -> SleepState:
        """
        Calculate sleep state based on aggregated data and time of day.
        time_of_day comes from FusionRules/StateEstimator.
        """
        now = time.time()
        time_since_motion = now - self.bedroom_last_motion
        
        new_state = "unknown"
        new_conf = 0.0
        
        if time_of_day == "night":
            if not self.bedroom_lights_on and time_since_motion > 1800: # 30 mins no motion in dark bedroom
                new_state = "sleeping"
                new_conf = 0.85
            elif self.bedroom_lights_on:
                new_state = "winding_down" # Or reading
                new_conf = 0.6
            else:
                new_state = "awake" # Moving in dark?
                new_conf = 0.4
        elif time_of_day == "morning":
            if time_since_motion < 300: # Recent motion
                new_state = "awake"
                new_conf = 0.9
            else:
                new_state = "sleeping" # Sleeping in?
                new_conf = 0.5
        else:
            new_state = "awake"
            new_conf = 0.95
            
        # Update state if changed
        if new_state != self.state:
            self.state = new_state
            self.confidence = new_conf
            self.last_state_change = now
            
        return SleepState(
            state=self.state,
            confidence=self.confidence,
            since_ts=self.last_state_change
        )
