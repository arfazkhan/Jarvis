from enum import Enum
from typing import Any, List, Optional, Dict, Union
from pydantic import BaseModel, Field

class AgentState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"
    WAITING_FOR_USER = "WAITING_FOR_USER"

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class ToolChoice(str, Enum):
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"

class Function(BaseModel):
    name: str
    arguments: str

class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: Function

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    
    @classmethod
    def user_message(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content)
    
    @classmethod
    def system_message(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)
    
    @classmethod
    def assistant_message(cls, content: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None) -> "Message":
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)
    
    @classmethod
    def tool_message(cls, content: str, tool_call_id: str, name: str) -> "Message":
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name)

    @classmethod
    def from_tool_calls(cls, tool_calls: List[ToolCall], content: str = "") -> "Message":
        """Create assistant message from tool calls"""
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

class Memory(BaseModel):
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = 100
    
    def add_message(self, message: Message):
        self.messages.append(message)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
    
    def get_recent(self, n: int) -> List[Message]:
        return self.messages[-n:]
    
    def clear(self):
        self.messages = []

# BMS Models
from .bms import (
    BMSDataPoint,
    Equipment,
    Alarm,
    EnergyReading,
    Anomaly,
    FailurePrediction,
    OpsInsight,
    PointType,
    PointQuality,
    EquipmentStatus,
    AlarmSeverity,
    AlarmState,
    EquipmentType,
)
