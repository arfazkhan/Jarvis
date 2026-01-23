"""
Tests for ARVIS Tool Collection (Production-Ready)
===================================================

Tests for:
- ToolCollection operations
- Parallel execution
- Health monitoring
"""

import asyncio
import json
import pytest

from agent_unified.tools.base import BaseTool, ToolResult, ToolConfig
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


class SlowMathTool(BaseTool):
    name: str = "slow_math"
    description: str = "Slow math for timing tests"
    parameters: dict = {
        "type": "object",
        "properties": {
            "delay": {"type": "number"}
        },
        "required": []
    }
    
    async def execute(self, delay: float = 0.5) -> ToolResult:
        await asyncio.sleep(delay)
        return self.success_response({"completed": True, "delay": delay})


class FailingMathTool(BaseTool):
    name: str = "failing_math"
    description: str = "Always fails"
    parameters: dict = {"type": "object", "properties": {}}
    
    async def execute(self) -> ToolResult:
        return self.fail_response("Intentional failure")


class TestToolCollection:
    """Tests for ToolCollection."""
    
    def test_add_tools(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        assert len(collection) == 2
        assert "add" in collection
        assert "multiply" in collection
    
    def test_add_tool_with_group(self):
        collection = ToolCollection()
        collection.add(AddTool(), group="math")
        collection.add(MultiplyTool(), group="math")
        
        math_tools = collection.get_by_group("math")
        assert len(math_tools) == 2
    
    def test_remove_tool(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        removed = collection.remove("add")
        
        assert removed is not None
        assert removed.name == "add"
        assert "add" not in collection
        assert len(collection) == 1
    
    def test_get_tool(self):
        collection = ToolCollection(AddTool())
        
        tool = collection.get("add")
        assert tool is not None
        assert tool.name == "add"
        
        missing = collection.get("missing")
        assert missing is None
    
    def test_bracket_access(self):
        collection = ToolCollection(AddTool())
        
        tool = collection["add"]
        assert tool.name == "add"
        
        with pytest.raises(KeyError):
            _ = collection["missing"]
    
    def test_iteration(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        names = [t.name for t in collection]
        assert "add" in names
        assert "multiply" in names
    
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
        
        result = await collection.execute("missing", a=1, b=2)
        
        assert not result.success
        assert "not found" in result.error


class TestParallelExecution:
    """Tests for parallel tool execution."""
    
    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        collection = ToolCollection(SlowMathTool(), AddTool(), MultiplyTool())
        
        calls = [
            {"name": "add", "args": {"a": 1, "b": 2}},
            {"name": "multiply", "args": {"a": 3, "b": 4}},
        ]
        
        start = asyncio.get_event_loop().time()
        results = await collection.execute_parallel(calls)
        elapsed = asyncio.get_event_loop().time() - start
        
        assert len(results) == 2
        assert all(r.success for r in results)
        
        # Should complete quickly since both are fast
        assert elapsed < 0.5
    
    @pytest.mark.asyncio
    async def test_parallel_with_slow_tools(self):
        collection = ToolCollection(SlowMathTool())
        
        # Two slow tools that each take 0.3s
        calls = [
            {"name": "slow_math", "args": {"delay": 0.3}},
            {"name": "slow_math", "args": {"delay": 0.3}},
        ]
        
        start = asyncio.get_event_loop().time()
        results = await collection.execute_parallel(calls)
        elapsed = asyncio.get_event_loop().time() - start
        
        assert len(results) == 2
        # Parallel execution should complete in ~0.3s, not 0.6s
        assert elapsed < 0.5
    
    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        calls = [
            {"name": "add", "args": {"a": 1, "b": 2}},
            {"name": "multiply", "args": {"a": 3, "b": 4}},
        ]
        
        results = await collection.execute_sequential(calls)
        
        assert len(results) == 2
        assert all(r.success for r in results)
    
    @pytest.mark.asyncio
    async def test_sequential_stop_on_error(self):
        collection = ToolCollection(AddTool(), FailingMathTool(), MultiplyTool())
        
        calls = [
            {"name": "add", "args": {"a": 1, "b": 2}},
            {"name": "failing_math", "args": {}},
            {"name": "multiply", "args": {"a": 3, "b": 4}},
        ]
        
        results = await collection.execute_sequential(calls, stop_on_error=True)
        
        # Should stop after failing tool
        assert len(results) == 2
        assert results[0].success
        assert not results[1].success


class TestCollectionHealth:
    """Tests for collection health monitoring."""
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        collection = ToolCollection(AddTool(), MultiplyTool())
        
        # Make some calls
        await collection.execute("add", a=1, b=2)
        await collection.execute("multiply", a=3, b=4)
        
        health = await collection.health_check()
        
        assert health["collection_healthy"] is True
        assert health["total_tools"] == 2
        assert health["healthy_tools"] == 2
        assert health["metrics"]["total_calls"] == 2
        assert health["metrics"]["successful_calls"] == 2
    
    @pytest.mark.asyncio
    async def test_metrics_with_failures(self):
        collection = ToolCollection(AddTool(), FailingMathTool())
        
        await collection.execute("add", a=1, b=2)
        await collection.execute("failing_math")
        
        health = await collection.health_check()
        
        assert health["metrics"]["failed_calls"] == 1
        assert "failing_math" in health["tools_with_errors"]


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


class TestCacheManagement:
    """Tests for cache management."""
    
    @pytest.mark.asyncio
    async def test_clear_all_caches(self):
        # Create tool with caching enabled
        add_tool = AddTool()
        add_tool.config.enable_cache = True
        
        collection = ToolCollection(add_tool)
        
        # Make a call (will be cached)
        await collection.execute("add", a=1, b=2)
        
        # Clear caches
        collection.clear_all_caches()
        
        # No exception = success
        assert True


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
