from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, PrivateAttr
from dataclasses import dataclass, field
import json


@dataclass
class ToolConfig:
    """Configuration for tool behavior"""
    timeout_seconds: float = 30.0
    max_retries: int = 3
    enable_cache: bool = False
    cache_ttl: int = 300
    rate_limit_calls: int = 0
    rate_limit_period: int = 60


# Decorators for backwards compatibility
def cacheable(func):
    """Decorator for cacheable methods (no-op for now)"""
    return func

def rate_limited(func):
    """Decorator for rate limited methods (no-op for now)"""
    return func


class ToolResult(BaseModel):
    """Standardized tool execution result"""
    output: Optional[Any] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None
    system: Optional[str] = None  # System instructions back to agent
    
    @property
    def success(self) -> bool:
        return self.error is None and self.output is not None
    
    def __bool__(self):
        return self.output is not None or self.error is not None
    
    def __str__(self):
        if self.error:
            return f"Error: {self.error}"
        return str(self.output)

class BaseTool(ABC, BaseModel):
    """Base class for all tools"""
    name: str
    description: str
    parameters: Optional[Dict] = None
    config: ToolConfig = field(default_factory=ToolConfig)
    
    def __init__(self, **data):
        if 'config' not in data:
            data['config'] = ToolConfig()
        super().__init__(**data)
    
    class Config:
        arbitrary_types_allowed = True
    
    async def __call__(self, **kwargs) -> ToolResult:
        return await self.execute(**kwargs)
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool"""
        pass
    
    def to_param(self) -> Dict:
        """Convert to OpenAI function format"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}}
            }
        }
    
    def success_response(self, data: Union[Dict, str], system: Optional[str] = None) -> ToolResult:
        output = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)
        return ToolResult(output=output, system=system)
    
    def fail_response(self, msg: str) -> ToolResult:
        return ToolResult(error=msg)

class Terminate(BaseTool):
    """Tool to terminate the agent execution"""
    name: str = "terminate"
    description: str = "Terminate the agent execution when goal is achieved or impossible"
    parameters: dict = {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Reason for termination"},
            "status": {"type": "string", "enum": ["success", "failure"]}
        },
        "required": ["reason", "status"]
    }
    
    async def execute(self, reason: str, status: str = "success") -> ToolResult:
        return self.success_response(f"Terminating: {status} - {reason}")
