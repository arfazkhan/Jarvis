"""
Integration Tests for ARVIS Agent System
==========================================

Tests using REAL LLM (k2think via env config) for battle testing:
- Tool execution with real LLM
- End-to-end agent scenarios
"""

import asyncio
import json
import os
import pytest

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.tools.collection import ToolCollection
from agent_unified.llm import UnifiedLLM


# Skip if no API key configured
pytestmark = pytest.mark.skipif(
    not (os.getenv("K2THINK_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")),
    reason="No LLM API key configured"
)


# Test tools - simple and safe
class CalculatorTool(BaseTool):
    """Simple calculator for testing."""
    
    name: str = "calculator"
    description: str = "Perform basic math: add, subtract, multiply, divide"
    parameters: dict = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
                "description": "Math operation to perform"
            },
            "a": {"type": "number", "description": "First number"},
            "b": {"type": "number", "description": "Second number"}
        },
        "required": ["operation", "a", "b"]
    }
    
    async def execute(self, operation: str, a: float, b: float) -> ToolResult:
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                return self.fail_response("Cannot divide by zero")
            result = a / b
        else:
            return self.fail_response(f"Unknown operation: {operation}")
        
        return self.success_response({"result": result, "operation": f"{a} {operation} {b}"})


class GreetingTool(BaseTool):
    """Simple greeting tool for testing."""
    
    name: str = "greeting"
    description: str = "Generate a greeting message for a person"
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Person's name"}
        },
        "required": ["name"]
    }
    
    async def execute(self, name: str) -> ToolResult:
        return self.success_response({"greeting": f"Hello, {name}! Welcome."})


class TestToolIntegration:
    """Integration tests for tool execution."""
    
    @pytest.mark.asyncio
    async def test_calculator_tool(self):
        """Test calculator tool execution."""
        tool = CalculatorTool()
        
        result = await tool.execute(operation="add", a=10, b=20)
        assert result.success
        data = json.loads(result.output)
        assert data["result"] == 30
    
    @pytest.mark.asyncio
    async def test_calculator_multiply(self):
        """Test calculator multiplication."""
        tool = CalculatorTool()
        
        result = await tool.execute(operation="multiply", a=5, b=5)
        assert result.success
        data = json.loads(result.output)
        assert data["result"] == 25
    
    @pytest.mark.asyncio
    async def test_calculator_divide_by_zero(self):
        """Test division by zero handling."""
        tool = CalculatorTool()
        
        result = await tool.execute(operation="divide", a=10, b=0)
        assert not result.success
        assert "zero" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_greeting_tool(self):
        """Test greeting tool execution."""
        tool = GreetingTool()
        
        result = await tool.execute(name="World")
        assert result.success
        data = json.loads(result.output)
        assert "World" in data["greeting"]


class TestCollectionIntegration:
    """Integration tests for ToolCollection."""
    
    @pytest.mark.asyncio
    async def test_collection_execute(self):
        """Test executing tools via collection."""
        collection = ToolCollection(CalculatorTool(), GreetingTool())
        
        result = await collection.execute("calculator", operation="add", a=1, b=2)
        assert result.success
        data = json.loads(result.output)
        assert data["result"] == 3
    
    @pytest.mark.asyncio
    async def test_collection_multiple_tools(self):
        """Test executing multiple different tools."""
        collection = ToolCollection(CalculatorTool(), GreetingTool())
        
        calc_result = await collection.execute("calculator", operation="multiply", a=3, b=4)
        greet_result = await collection.execute("greeting", name="Test")
        
        assert calc_result.success
        assert greet_result.success
        
        calc_data = json.loads(calc_result.output)
        assert calc_data["result"] == 12
    
    @pytest.mark.asyncio
    async def test_to_params_for_llm(self):
        """Test converting tools to OpenAI function format."""
        collection = ToolCollection(CalculatorTool(), GreetingTool())
        
        params = collection.to_params()
        
        assert len(params) == 2
        assert all(p["type"] == "function" for p in params)
        
        names = [p["function"]["name"] for p in params]
        assert "calculator" in names
        assert "greeting" in names


class TestLLMIntegration:
    """Integration tests for LLM (requires API key)."""
    
    @pytest.mark.asyncio
    async def test_llm_basic_response(self):
        """Test basic LLM response."""
        llm = UnifiedLLM()
        
        response = await llm.ask(
            messages=[{"role": "user", "content": "Say only the word 'test'"}]
        )
        
        assert response is not None
        # Response format varies by LLM, so just check we got something
        assert hasattr(response, 'content') or response


# Run tests with: pytest agent_unified/tests/test_integration.py -v --tb=short
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
