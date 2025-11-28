"""
Mission Base Models
-------------------
Core data structures for mission system.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
import time

class MissionStatus(Enum):
    """Mission lifecycle states"""
    INIT = "init"
    PLANNING = "planning"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    ADAPTING = "adapting"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"

@dataclass
class Mission:
    """
    Represents a multi-day autonomous mission.
    """
    mission_id: str
    mission_type: Literal["sleep_optimization", "energy_saver", "home_security", "focus_productivity"]
    status: MissionStatus
    plan: Optional[Dict[str, Any]] = None  # DAG representation
    context: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    start_ts: float = field(default_factory=time.time)
    next_run_ts: Optional[float] = None
    confidence: float = 0.0
    user_id: str = "default_user"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_type": self.mission_type,
            "status": self.status.value,
            "plan": self.plan,
            "context": self.context,
            "metrics": self.metrics,
            "history": self.history,
            "start_ts": self.start_ts,
            "next_run_ts": self.next_run_ts,
            "confidence": self.confidence,
            "user_id": self.user_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Mission':
        data["status"] = MissionStatus(data["status"])
        return cls(**data)
