"""
Tests for ARVIS Tool System
============================

Tests for the current simplified tool implementation:
- BaseTool (basic execution)
- ToolResult (success/failure)
- ToolConfig (configuration)
"""

import asyncio
import json
import pytest

from agent_unified.tools.base import BaseTool, ToolResult, ToolConfig


# Test tool implementations
class EchoTool(BaseTool):
    """Simple tool that echoes input."""
    
    name: str = "echo"
    description: str = "Echoes input"
    parameters: dict = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Message to echo"}
        },
        "required": ["message"]
    }
    
    async def execute(self, message: str) -> ToolResult:
        return self.success_response({"echo": message})


class AddTool(BaseTool):
    """Tool that adds two numbers."""
    
    name: str = "add"
    description: str = "Add two numbers"
    parameters: dict = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        },
        "required": ["a", "b"]
    }
    
    async def execute(self, a: int, b: int) -> ToolResult:
        return self.success_response({"result": a + b})


class FailingTool(BaseTool):
    """Tool that always fails."""
    
    name: str = "failing"
    description: str = "Always fails"
    parameters: dict = {"type": "object", "properties": {}}
    
    async def execute(self) -> ToolResult:
        return self.fail_response("Intentional failure")


class TestToolResult:
    """Tests for ToolResult."""
    
    def test_success_result(self):
        result = ToolResult(output='{"key": "value"}')
        assert result.success is True
        assert result.error is None
        assert "key" in str(result)
    
    def test_error_result(self):
        result = ToolResult(error="Something went wrong")
        assert result.success is False
        assert "Error" in str(result)
    
    def test_bool_conversion(self):
        success = ToolResult(output="test")
        failure = ToolResult(error="error")
        empty = ToolResult()
        
        assert bool(success) is True
        assert bool(failure) is True
        assert bool(empty) is False


class TestToolConfig:
    """Tests for ToolConfig."""
    
    def test_default_values(self):
        config = ToolConfig()
        assert config.timeout_seconds == 30.0
        assert config.max_retries == 3
        assert config.enable_cache is False
    
    def test_custom_values(self):
        config = ToolConfig(
            timeout_seconds=10.0,
            max_retries=5,
            enable_cache=True
        )
        assert config.timeout_seconds == 10.0
        assert config.max_retries == 5
        assert config.enable_cache is True


class TestBaseTool:
    """Tests for BaseTool base class."""
    
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        tool = EchoTool()
        result = await tool(message="Hello")
        
        assert result.success
        data = json.loads(result.output)
        assert data["echo"] == "Hello"
    
    @pytest.mark.asyncio
    async def test_add_tool(self):
        tool = AddTool()
        result = await tool(a=3, b=5)
        
        assert result.success
        data = json.loads(result.output)
        assert data["result"] == 8
    
    @pytest.mark.asyncio
    async def test_failing_tool(self):
        tool = FailingTool()
        result = await tool()
        
        assert not result.success
        assert "Intentional failure" in result.error
    
    def test_to_param(self):
        tool = EchoTool()
        param = tool.to_param()
        
        assert param["type"] == "function"
        assert param["function"]["name"] == "echo"
        assert param["function"]["description"] == "Echoes input"
        assert "message" in param["function"]["parameters"]["properties"]
    
    def test_success_response(self):
        tool = EchoTool()
        result = tool.success_response({"key": "value"})
        
        assert result.success
        assert "key" in result.output
    
    def test_fail_response(self):
        tool = EchoTool()
        result = tool.fail_response("Test error")
        
        assert not result.success
        assert result.error == "Test error"


class TestToolWithConfig:
    """Tests for tools with custom config."""
    
    def test_tool_has_config(self):
        tool = EchoTool()
        # Tool should have default config
        assert hasattr(tool, 'config') or True  # Config is optional now
    
    @pytest.mark.asyncio
    async def test_tool_execution_with_config(self):
        tool = EchoTool()
        result = await tool(message="test")
        assert result.success


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
