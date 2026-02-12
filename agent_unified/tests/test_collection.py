"""
Tests for ARVIS Tool Collection
================================

Tests for the current simplified ToolCollection implementation:
- Basic collection operations
- Tool execution
- Parameter conversion
"""

import asyncio
import json
import pytest

from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.tools.collection import ToolCollection


# Test tools
class AddTool(BaseTool):
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


class MultiplyTool(BaseTool):
    name: str = "multiply"
    description: str = "Multiply two numbers"
    parameters: dict = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        },
        "required": ["a", "b"]
    }
    
    async def execute(self, a: int, b: int) -> ToolResult:
        return self.success_response({"result": a * b})


class FailingTool(BaseTool):
    name: str = "failing"
    description: str = "Always fails"
    parameters: dict = {"type": "object", "properties": {}}
    
    async def execute(self) -> ToolResult:
        return self.fail_response("Intentional failure")


class TestToolCollection:
    """Tests for ToolCollection."""
    
    def test_create_collection(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        assert len(collection.tools) == 2
    
    def test_add_tools(self):
        collection = ToolCollection(AddTool())
        collection.add_tools(MultiplyTool())
        assert len(collection.tools) == 2
    
    def test_get_tool(self):
        collection = ToolCollection(AddTool())
        
        tool = collection.get_tool("add")
        assert tool is not None
        assert tool.name == "add"
        
        missing = collection.get_tool("nonexistent")
        assert missing is None
    
    @pytest.mark.asyncio
    async def test_execute(self):
        collection = ToolCollection(AddTool())
        
        result = await collection.execute("add", a=3, b=5)
        
        assert result.success
        data = json.loads(result.output)
        assert data["result"] == 8
    
    @pytest.mark.asyncio
    async def test_execute_missing_tool(self):
        collection = ToolCollection(AddTool())
        
        result = await collection.execute("nonexistent", a=1, b=2)
        
        assert not result.success
        assert "not found" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_failing_tool(self):
        collection = ToolCollection(FailingTool())
        
        result = await collection.execute("failing")
        
        assert not result.success
        assert "Intentional failure" in result.error


class TestToParams:
    """Tests for OpenAI function format conversion."""
    
    def test_to_params(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        params = collection.to_params()
        
        assert len(params) == 2
        assert all(p["type"] == "function" for p in params)
        
        names = [p["function"]["name"] for p in params]
        assert "add" in names
        assert "multiply" in names
    
    def test_to_params_empty(self):
        collection = ToolCollection()
        params = collection.to_params()
        assert params == []


class TestToolMapConsistency:
    """Tests for tool_map consistency."""
    
    def test_tool_map_created_on_init(self):
        add_tool = AddTool()
        multiply_tool = MultiplyTool()
        collection = ToolCollection(add_tool, multiply_tool)
        
        assert "add" in collection.tool_map
        assert "multiply" in collection.tool_map
    
    def test_tool_map_updated_on_add(self):
        collection = ToolCollection(AddTool())
        assert len(collection.tool_map) == 1
        
        collection.add_tools(MultiplyTool())
        assert len(collection.tool_map) == 2
        assert "multiply" in collection.tool_map


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
