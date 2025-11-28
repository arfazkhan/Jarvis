"""
Mission Step
------------
Represents a single step in a mission plan.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class StepType(Enum):
    """Types of mission steps"""
    COLLECTION = "collection"  # Data collection
    SCENE = "scene"  # Scene generation/application
    AUTOMATION = "automation"  # Automation scheduling
    MONITORING = "monitoring"  # Continuous monitoring
    ACTION = "action"  # Direct device action

class StepStatus(Enum):
    """Step execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"

@dataclass
class MissionStep:
    """
    Single executable step in a mission.
    """
    step_id: str
    step_type: StepType
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    timeout: int = 60  # seconds
    retry_count: int = 2
    status: StepStatus = StepStatus.PENDING
    outputs: Dict[str, Any] = field(default_factory=dict)
    continuous: bool = False  # For monitoring steps
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "status": self.status.value,
            "outputs": self.outputs,
            "continuous": self.continuous
        }
