"""
Mission Result
--------------
Result of mission execution.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List
import time

@dataclass
class MissionResult:
    """
    Outcome of a mission execution.
    """
    mission_id: str
    success: bool
    metrics_achieved: Dict[str, float] = field(default_factory=dict)
    steps_completed: List[str] = field(default_factory=list)
    steps_failed: List[str] = field(default_factory=list)
    error_message: str = ""
    completion_ts: float = field(default_factory=time.time)
    duration: float = 0.0  # seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "success": self.success,
            "metrics_achieved": self.metrics_achieved,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "error_message": self.error_message,
            "completion_ts": self.completion_ts,
            "duration": self.duration
        }
