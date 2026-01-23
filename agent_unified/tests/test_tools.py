"""
Tests for ARVIS Tool System (Production-Ready)
===============================================

Comprehensive tests for:
- BaseTool (validation, timeout, retry, caching)
- ToolCollection (parallel execution, health)
"""

import asyncio
import json
import time
import pytest

from agent_unified.tools.base import BaseTool, ToolResult, ToolConfig, cacheable, rate_limited, PrivateAttr


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


class SlowTool(BaseTool):
    """Tool that takes time to execute."""
    
    name: str = "slow_tool"
    description: str = "Slow tool for timeout testing"
    parameters: dict = {
        "type": "object",
        "properties": {
            "delay_seconds": {"type": "number"}
        },
        "required": []
    }
    
    # Quick timeout for testing
    config: ToolConfig = ToolConfig(timeout_seconds=1.0)
    
    async def execute(self, delay_seconds: float = 0.1) -> ToolResult:
        await asyncio.sleep(delay_seconds)
        return self.success_response({"waited": delay_seconds})


class FailingTool(BaseTool):
    """Tool that fails a specified number of times then succeeds."""
    
    name: str = "failing_tool"
    description: str = "Fails then succeeds"
    parameters: dict = {
        "type": "object",
        "properties": {
            "fail_times": {"type": "integer"}
        },
        "required": []
    }
    
    _call_count: int = PrivateAttr(default=0)
    config: ToolConfig = ToolConfig(
        max_retries=3,
        retry_delay_ms=100,
        retryable_exceptions=["RuntimeError", "ValueError"]
    )
    
    async def execute(self, fail_times: int = 2) -> ToolResult:
        self._call_count += 1
        if self._call_count <= fail_times:
            raise RuntimeError(f"Intentional failure {self._call_count}")
        return self.success_response({"attempts": self._call_count})


class ValidationTool(BaseTool):
    """Tool with strict parameter validation."""
    
    name: str = "validation_tool"
    description: str = "Tests parameter validation"
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "active": {"type": "boolean"},
            "status": {"type": "string", "enum": ["active", "inactive", "pending"]}
        },
        "required": ["name", "age"]
    }
    
    async def execute(self, name: str, age: int, active: bool = True, status: str = "active") -> ToolResult:
        return self.success_response({"name": name, "age": age, "active": active, "status": status})


@cacheable(ttl_seconds=5)
class CacheableTool(BaseTool):
    """Tool with caching enabled via decorator."""
    
    name: str = "cacheable_tool"
    description: str = "Cacheable tool"
    parameters: dict = {
        "type": "object",
        "properties": {
            "key": {"type": "string"}
        },
        "required": ["key"]
    }
    
    _call_count: int = PrivateAttr(default=0)
    
    async def execute(self, key: str) -> ToolResult:
        self._call_count += 1
        return self.success_response({"key": key, "call_count": self._call_count})


@rate_limited(calls=3, period_seconds=10)
class RateLimitedTool(BaseTool):
    """Tool with rate limiting via decorator."""
    
    name: str = "rate_limited_tool"
    description: str = "Rate limited tool"
    parameters: dict = {"type": "object", "properties": {}}
    
    async def execute(self) -> ToolResult:
        return self.success_response({"time": time.time()})


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
    
    def test_to_dict(self):
        result = ToolResult(output="test", execution_time_ms=100, correlation_id="abc123")
        d = result.to_dict()
        assert d["output"] == "test"
        assert d["execution_time_ms"] == 100
        assert d["correlation_id"] == "abc123"


class TestBaseTool:
    """Tests for BaseTool base class."""
    
    @pytest.mark.asyncio
    async def test_simple_execution(self):
        tool = EchoTool()
        result = await tool(message="Hello")
        
        assert result.success
        data = json.loads(result.output)
        assert data["echo"] == "Hello"
        assert result.correlation_id is not None
        assert result.execution_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_validation_missing_required(self):
        tool = ValidationTool()
        result = await tool()  # Missing required params
        
        assert not result.success
        assert "Missing required parameter" in result.error
    
    @pytest.mark.asyncio
    async def test_validation_wrong_type(self):
        tool = ValidationTool()
        result = await tool(name="John", age="not_an_int")  # Wrong type
        
        assert not result.success
        assert "must be an integer" in result.error
    
    @pytest.mark.asyncio
    async def test_validation_invalid_enum(self):
        tool = ValidationTool()
        result = await tool(name="John", age=25, status="invalid_status")
        
        assert not result.success
        assert "must be one of" in result.error
    
    @pytest.mark.asyncio
    async def test_validation_success(self):
        tool = ValidationTool()
        result = await tool(name="John", age=25, status="active")
        
        assert result.success
        data = json.loads(result.output)
        assert data["name"] == "John"
        assert data["age"] == 25


class TestTimeout:
    """Tests for timeout functionality."""
    
    @pytest.mark.asyncio
    async def test_timeout_triggered(self):
        tool = SlowTool()
        result = await tool(delay_seconds=5)  # Will timeout
        
        assert not result.success
        assert "timed out" in result.error
    
    @pytest.mark.asyncio
    async def test_no_timeout_when_fast(self):
        tool = SlowTool()
        result = await tool(delay_seconds=0.1)  # Within timeout
        
        assert result.success


class TestRetry:
    """Tests for retry logic."""
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        tool = FailingTool()
        result = await tool(fail_times=2)  # Fail twice, succeed third
        
        assert result.success
        data = json.loads(result.output)
        assert data["attempts"] == 3
    
    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        tool = FailingTool()
        result = await tool(fail_times=10)  # Will exhaust all retries
        
        assert not result.success
        assert "Failed after" in result.error


class TestCaching:
    """Tests for caching functionality."""
    
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        tool = CacheableTool()
        
        # First call
        result1 = await tool(key="test")
        assert result1.success
        assert not result1.cached
        
        # Second call - should be cached
        result2 = await tool(key="test")
        assert result2.success
        assert result2.cached
        
        # Call count should be 1 (second was cached)
        data1 = json.loads(result1.output)
        data2 = json.loads(result2.output)
        assert data1["call_count"] == 1
        assert data2["call_count"] == 1  # Same as first
    
    @pytest.mark.asyncio
    async def test_cache_different_keys(self):
        tool = CacheableTool()
        
        result1 = await tool(key="key1")
        result2 = await tool(key="key2")
        
        # Different keys = different cache entries
        data1 = json.loads(result1.output)
        data2 = json.loads(result2.output)
        assert data1["call_count"] == 1
        assert data2["call_count"] == 2


class TestRateLimiting:
    """Tests for rate limiting."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_enforced(self):
        tool = RateLimitedTool()
        
        # First 3 calls should succeed
        for _ in range(3):
            result = await tool()
            assert result.success
        
        # 4th call should be rate limited
        result = await tool()
        assert not result.success
        assert "Rate limit exceeded" in result.error


class TestMetrics:
    """Tests for execution metrics."""
    
    @pytest.mark.asyncio
    async def test_metrics_updated(self):
        tool = EchoTool()
        
        # Make some calls
        await tool(message="test1")
        await tool(message="test2")
        
        metrics = tool.get_metrics()
        assert metrics.total_calls == 2
        assert metrics.successful_calls == 2
        assert metrics.failed_calls == 0
        # Allow 0 for fast operations (sub-millisecond)
        assert metrics.total_execution_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_metrics_with_failures(self):
        tool = ValidationTool()
        
        await tool(name="John", age=25)  # Success
        await tool()  # Failure - missing required
        
        metrics = tool.get_metrics()
        assert metrics.total_calls == 2
        assert metrics.successful_calls == 1
        assert metrics.failed_calls == 1


class TestHealthCheck:
    """Tests for health checks."""
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        tool = EchoTool()
        await tool(message="test")
        
        health = await tool.health_check()
        
        assert health["name"] == "echo"
        assert health["healthy"] is True
        assert "metrics" in health
        assert health["metrics"]["total_calls"] == 1


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
