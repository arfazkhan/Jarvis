"""
ARVIS Unified Tool Base
=======================

Base classes for all tools combining OpenManus patterns with ARVIS needs.

Provides:
- ToolResult: Standardized execution result
- BaseTool: Abstract base for all tools
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# TOOL RESULT
# ═══════════════════════════════════════════════════════════════════════════

class ToolResult(BaseModel):
    """Standardized tool execution result"""
    
    output: Optional[Any] = Field(default=None, description="Tool output data")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    base64_image: Optional[str] = Field(default=None, description="Base64 encoded image")
    system: Optional[str] = Field(default=None, description="System message for agent")
    
    class Config:
        arbitrary_types_allowed = True
    
    def __bool__(self) -> bool:
        """Result is truthy if it has any content"""
        return any(getattr(self, f) for f in self.model_fields)
    
    def __add__(self, other: "ToolResult") -> "ToolResult":
        """Combine two results"""
        def combine(a: Optional[str], b: Optional[str]) -> Optional[str]:
            if a and b:
                return a + b
            return a or b
        
        return ToolResult(
            output=combine(str(self.output) if self.output else None, 
                          str(other.output) if other.output else None),
            error=combine(self.error, other.error),
            base64_image=self.base64_image or other.base64_image,
            system=combine(self.system, other.system)
        )
    
    def __str__(self) -> str:
        """String representation"""
        if self.error:
            return f"Error: {self.error}"
        return str(self.output) if self.output else ""
    
    @property
    def is_success(self) -> bool:
        """Check if result is successful"""
        return self.error is None and self.output is not None
    
    @property
    def is_error(self) -> bool:
        """Check if result is an error"""
        return self.error is not None


# ═══════════════════════════════════════════════════════════════════════════
# BASE TOOL
# ═══════════════════════════════════════════════════════════════════════════

class BaseTool(ABC, BaseModel):
    """
    Base class for all tools.
    
    Provides:
    - Pydantic model validation
    - OpenAI function calling format conversion
    - Standardized success/fail responses
    
    All tools must implement the execute() method.
    """
    
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    parameters: Optional[Dict] = Field(default=None, description="JSON schema for parameters")
    
    class Config:
        arbitrary_types_allowed = True
    
    async def __call__(self, **kwargs) -> ToolResult:
        """Execute the tool"""
        return await self.execute(**kwargs)
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters. Must be implemented by subclasses."""
        pass
    
    def to_param(self) -> Dict:
        """
        Convert tool to OpenAI function calling format.
        
        Returns:
            Dict in OpenAI tool format
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
    def success_response(self, data: Union[Dict[str, Any], str, Any]) -> ToolResult:
        """
        Create a successful tool result.
        
        Args:
            data: Result data (dict, string, or any serializable object)
            
        Returns:
            ToolResult with output
        """
        if isinstance(data, str):
            output = data
        elif isinstance(data, dict):
            output = json.dumps(data, indent=2, default=str)
        else:
            output = str(data)
        return ToolResult(output=output)
    
    def fail_response(self, msg: str) -> ToolResult:
        """
        Create a failed tool result.
        
        Args:
            msg: Error message
            
        Returns:
            ToolResult with error
        """
        return ToolResult(error=msg)
    
    def image_response(self, base64_image: str, caption: str = "") -> ToolResult:
        """
        Create a tool result with an image.
        
        Args:
            base64_image: Base64 encoded image data
            caption: Optional caption
            
        Returns:
            ToolResult with image and caption
        """
        return ToolResult(output=caption, base64_image=base64_image)


# ═══════════════════════════════════════════════════════════════════════════
# SPECIALIZED RESULTS
# ═══════════════════════════════════════════════════════════════════════════

class CLIResult(ToolResult):
    """Tool result that can be rendered as CLI output"""
    pass


class ToolFailure(ToolResult):
    """Tool result representing a failure"""
    
    def __init__(self, error: str, **kwargs):
        super().__init__(error=error, **kwargs)
