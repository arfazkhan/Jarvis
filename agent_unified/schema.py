"""
ARVIS Unified Schema
====================

Core data models combining OpenManus patterns with ARVIS needs.

Provides:
- Message: Chat message with role, content, tool calls
- Memory: Message history with limit
- AgentState: IDLE, RUNNING, FINISHED, ERROR
- ToolChoice: NONE, AUTO, REQUIRED
- ToolCall: Function call representation
"""

from enum import Enum
from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class Role(str, Enum):
    """Message role options"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class ToolChoice(str, Enum):
    """Tool choice options for LLM"""
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


# ═══════════════════════════════════════════════════════════════════════════
# TOOL CALL MODELS
# ═══════════════════════════════════════════════════════════════════════════

class Function(BaseModel):
    """Function call details"""
    name: str
    arguments: str  # JSON string


class ToolCall(BaseModel):
    """Represents a tool/function call in a message"""
    id: str
    type: str = "function"
    function: Function


# ═══════════════════════════════════════════════════════════════════════════
# MESSAGE
# ═══════════════════════════════════════════════════════════════════════════

class Message(BaseModel):
    """Represents a chat message in the conversation"""
    
    role: str = Field(...)
    content: Optional[str] = Field(default=None)
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    name: Optional[str] = Field(default=None)
    tool_call_id: Optional[str] = Field(default=None)
    base64_image: Optional[str] = Field(default=None)
    
    def __add__(self, other) -> List["Message"]:
        """Support Message + list or Message + Message"""
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Message):
            return [self, other]
        raise TypeError(f"Unsupported operand for +: {type(other)}")
    
    def __radd__(self, other) -> List["Message"]:
        """Support list + Message"""
        if isinstance(other, list):
            return other + [self]
        raise TypeError(f"Unsupported operand for +: {type(other)}")
    
    def to_dict(self) -> dict:
        """Convert message to dictionary format"""
        msg = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls is not None:
            msg["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
        if self.name is not None:
            msg["name"] = self.name
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.base64_image is not None:
            msg["base64_image"] = self.base64_image
        return msg
    
    @classmethod
    def user_message(cls, content: str, base64_image: Optional[str] = None) -> "Message":
        """Create a user message"""
        return cls(role=Role.USER.value, content=content, base64_image=base64_image)
    
    @classmethod
    def system_message(cls, content: str) -> "Message":
        """Create a system message"""
        return cls(role=Role.SYSTEM.value, content=content)
    
    @classmethod
    def assistant_message(cls, content: Optional[str] = None, base64_image: Optional[str] = None) -> "Message":
        """Create an assistant message"""
        return cls(role=Role.ASSISTANT.value, content=content, base64_image=base64_image)
    
    @classmethod
    def tool_message(cls, content: str, tool_call_id: str, name: str, base64_image: Optional[str] = None) -> "Message":
        """Create a tool response message"""
        return cls(
            role=Role.TOOL.value,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image
        )
    
    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs
    ) -> "Message":
        """Create Message from raw LLM tool calls"""
        formatted_calls = [
            ToolCall(
                id=tc.id,
                function=Function(
                    name=tc.function.name,
                    arguments=tc.function.arguments
                )
            )
            for tc in tool_calls
        ]
        return cls(
            role=Role.ASSISTANT.value,
            content=content if isinstance(content, str) else "\n".join(content),
            tool_calls=formatted_calls,
            base64_image=base64_image,
            **kwargs
        )


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY
# ═══════════════════════════════════════════════════════════════════════════

class Memory(BaseModel):
    """Agent memory store with message history"""
    
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = Field(default=100)
    
    def add_message(self, message: Message) -> None:
        """Add a message to memory"""
        self.messages.append(message)
        # Enforce message limit
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
    
    def add_messages(self, messages: List[Message]) -> None:
        """Add multiple messages"""
        for msg in messages:
            self.add_message(msg)
    
    def clear(self) -> None:
        """Clear all messages"""
        self.messages.clear()
    
    def get_recent(self, n: int) -> List[Message]:
        """Get n most recent messages"""
        return self.messages[-n:]
    
    def to_dict_list(self) -> List[dict]:
        """Convert messages to list of dicts"""
        return [msg.to_dict() for msg in self.messages]
    
    def get_by_role(self, role: str) -> List[Message]:
        """Get all messages with specific role"""
        return [msg for msg in self.messages if msg.role == role]
    
    def get_last_assistant_message(self) -> Optional[Message]:
        """Get the last assistant message"""
        for msg in reversed(self.messages):
            if msg.role == Role.ASSISTANT.value:
                return msg
        return None
