"""
Sensor Models
-------------
Core data models for the Sensor Fusion layer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal
import time

@dataclass
class Sensor:
    id: str
    type: str          # "motion", "contact", "temp", "wifi_presence", "light_level", ...
    room: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict) # {"device_id": "...", "vendor": "..."}

@dataclass
class SensorEvent:
    sensor_id: str
    sensor_type: str
    room: Optional[str]
    value: Any         # bool / float / str / enum
    ts: float = field(default_factory=time.time)
    source: str = "physical" # "physical" | "virtual" | "sim"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type,
            "room": self.room,
            "value": self.value,
            "ts": self.ts,
            "source": self.source
        }

@dataclass
class RoomOccupancy:
    room: str
    is_occupied: bool
    confidence: float   # 0.0 – 1.0
    last_change_ts: float

@dataclass
class HomePresence:
    state: Literal["home", "away", "unknown"]
    confidence: float
    sources: List[str]  # ["wifi_presence", "door_contact", ...]

@dataclass
class SleepState:
    state: Literal["awake", "winding_down", "sleeping", "unknown"]
    confidence: float
    since_ts: float

@dataclass
class EmotionalState:
    state: Literal["neutral", "happy", "sad", "stressed", "tired", "excited"]
    confidence: float
    updated_ts: float

@dataclass
class HomeSituation:
    time_of_day: Literal["morning", "day", "evening", "night"]
    home_presence: HomePresence
    room_occupancy: Dict[str, RoomOccupancy]
    sleep_state: SleepState
    activity_hint: Optional[str]        # "cooking", "working", "relaxing", ...
    emotional_state: EmotionalState
    updated_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_of_day": self.time_of_day,
            "home_presence": self.home_presence.__dict__,
            "room_occupancy": {k: v.__dict__ for k, v in self.room_occupancy.items()},
            "sleep_state": self.sleep_state.__dict__,
            "activity_hint": self.activity_hint,
            "emotional_state": self.emotional_state.__dict__,
            "updated_ts": self.updated_ts
        }
