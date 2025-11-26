"""
Fusion Rules
------------
Pure functions for high-level inference based on sensor data.
"""

import time
from typing import Literal, Dict, Optional
from agent_sensors.sensor_models import RoomOccupancy, SleepState, HomePresence

def infer_time_of_day(ts: float = None) -> Literal["morning", "day", "evening", "night"]:
    """Infer time of day based on local hour"""
    if ts is None:
        ts = time.time()
    
    hour = time.localtime(ts).tm_hour
    
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "day"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"

def infer_activity_hint(
    time_of_day: str,
    presence: HomePresence,
    occupancy: Dict[str, RoomOccupancy],
    sleep_state: SleepState
) -> Optional[str]:
    """
    Infer coarse activity hint.
    """
    if presence.state == "away":
        return None
        
    # Check occupied rooms first (overrides sleep state if active)
    occupied_rooms = [r for r, occ in occupancy.items() if occ.is_occupied]
    
    if "kitchen" in occupied_rooms:
        if time_of_day in ["morning", "evening"]:
            return "cooking"
        if time_of_day == "night":
            return "snacking"
            
    if "living_room" in occupied_rooms:
        if time_of_day == "evening":
            return "relaxing"
            
    if "office" in occupied_rooms:
        if time_of_day == "day":
            return "working"

    if sleep_state.state == "sleeping":
        return "sleeping"
    
    if sleep_state.state == "winding_down":
        return "relaxing"
            
    return None
