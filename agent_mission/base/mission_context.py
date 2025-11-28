"""
Mission Context
---------------
Contextual information for mission execution.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import time

@dataclass
class MissionContext:
    """
    Runtime context for a mission.
    Includes sensor state, user preferences, temporal info.
    """
    user_id: str
    home_situation: Optional[Dict[str, Any]] = None  # Current HomeSituation snapshot
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    temporal_info: Dict[str, Any] = field(default_factory=dict)  # Time windows, schedules
    constraints: Dict[str, Any] = field(default_factory=dict)  # Safety, rate limits
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional context
    created_ts: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "home_situation": self.home_situation,
            "user_preferences": self.user_preferences,
            "temporal_info": self.temporal_info,
            "constraints": self.constraints,
            "metadata": self.metadata,
            "created_ts": self.created_ts
        }
