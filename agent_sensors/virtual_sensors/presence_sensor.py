"""
Presence Sensor (Virtual)
-------------------------
Infers Home/Away state based on WiFi and Door events.
Heuristics:
- Any known WiFi device present = Home (High Confidence)
- Door Open + All WiFi Lost = Away
- No Motion > 2h + No WiFi = Away
"""

import time
from typing import Dict, Set, List
from agent_sensors.sensor_models import SensorEvent, HomePresence

class PresenceSensor:
    def __init__(self, wifi_grace_period: float = 60.0):
        self.known_devices: Set[str] = set() # Set of sensor_ids (wifi) currently present
        self.last_door_event_ts: float = 0
        self.last_motion_ts: float = 0
        self.wifi_grace_period = wifi_grace_period
        self.last_wifi_disconnect_ts: Dict[str, float] = {} # device -> disconnect_ts

    def update_from_event(self, event: SensorEvent):
        if event.sensor_type == "wifi_presence":
            if event.value: # Connected
                self.known_devices.add(event.sensor_id)
                if event.sensor_id in self.last_wifi_disconnect_ts:
                    del self.last_wifi_disconnect_ts[event.sensor_id]
            else: # Disconnected
                self.known_devices.discard(event.sensor_id)
                self.last_wifi_disconnect_ts[event.sensor_id] = event.ts
                
        elif event.sensor_type == "contact" and "door" in event.sensor_id:
            if event.value: # Open
                self.last_door_event_ts = event.ts
                
        elif event.sensor_type == "motion":
            if event.value:
                self.last_motion_ts = event.ts

    def get_home_presence(self) -> HomePresence:
        now = time.time()
        
        # Rule 1: WiFi Presence (Strongest Signal)
        # Check active devices OR devices within grace period
        active_devices = list(self.known_devices)
        
        # Check grace period for disconnected devices
        for dev, ts in self.last_wifi_disconnect_ts.items():
            if now - ts < self.wifi_grace_period:
                active_devices.append(dev)
        
        if active_devices:
            return HomePresence(
                state="home",
                confidence=0.95,
                sources=active_devices
            )
            
        # Rule 2: No WiFi
        # If door opened recently and then wifi lost -> Likely left
        # If no motion for long time -> Likely away
        
        time_since_motion = now - self.last_motion_ts
        
        if time_since_motion > 7200: # 2 hours
            return HomePresence(
                state="away",
                confidence=0.8,
                sources=["timeout"]
            )
            
        # Default: Unknown (or assume home if short time since motion)
        if time_since_motion < 1800: # 30 mins
            return HomePresence(
                state="home",
                confidence=0.4, # Low confidence because no wifi
                sources=["recent_motion"]
            )
            
        return HomePresence(
            state="unknown",
            confidence=0.0,
            sources=[]
        )
