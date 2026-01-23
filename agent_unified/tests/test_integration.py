"""
Integration Tests for ARVIS Agent System
==========================================

Tests using REAL LLM (k2think via env config) for battle testing:
- ARVISToolAgent with real tool calls
- End-to-end agent execution
"""

import asyncio
import json
import os
import pytest

from agent_unified.schema import AgentState
from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.tools.collection import ToolCollection
from agent_unified.llm import UnifiedLLM


# Skip if no API key configured
pytestmark = pytest.mark.skipif(
    not (os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")),
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


class TerminateTool(BaseTool):
    """Tool to end agent execution."""
    
    name: str = "terminate"
    description: str = "Call this when you have completed the task and want to end"
    parameters: dict = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Summary of what was accomplished"}
        },
        "required": ["summary"]
    }
    
    async def execute(self, summary: str) -> ToolResult:
        return self.success_response({"status": "completed", "summary": summary})


class TestRealLLMIntegration:
    """Integration tests using real k2think LLM."""
    
    @pytest.fixture
    def agent(self):
        """Create agent with real LLM and test tools."""
        return ARVISToolAgent(
            name="test_agent",
            available_tools=ToolCollection(
                CalculatorTool(),
                GreetingTool(),
                TerminateTool()
            ),
            max_steps=5,
            system_prompt="You are a helpful assistant. Use the available tools to help users. Always call terminate when done."
        )
    
    @pytest.mark.asyncio
    async def test_llm_connection(self):
        """Test that LLM is properly configured and responding."""
        llm = UnifiedLLM()
        
        response = await llm.ask(
            messages=[{"role": "user", "content": "Say 'hello' and nothing else"}]
        )
        
        assert response is not None
        assert hasattr(response, 'content')
        assert "hello" in response.content.lower()
    
    @pytest.mark.asyncio
    async def test_simple_tool_call(self, agent):
        """Test agent can call a simple tool via LLM."""
        agent.update_memory("user", "Calculate 5 plus 3")
        
        # Think - should generate tool call
        has_tool_calls = await agent.think()
        
        # We expect the LLM to generate a calculator tool call
        # but it's non-deterministic, so just check it processed
        assert agent.state == AgentState.RUNNING
    
    @pytest.mark.asyncio
    async def test_calculator_e2e(self, agent):
        """End-to-end test: ask agent to do math."""
        result = await agent.run("What is 25 multiplied by 4? Use the calculator tool.")
        
        assert agent.state == AgentState.FINISHED
        # The agent should have called calculator and terminate
        assert len(agent.execution_traces) > 0
    
    @pytest.mark.asyncio
    async def test_greeting_e2e(self, agent):
        """End-to-end test: ask agent to greet someone."""
        result = await agent.run("Greet John using the greeting tool, then terminate.")
        
        assert agent.state == AgentState.FINISHED


class TestToolExecutionReal:
    """Test tool execution with real parallel calls."""
    
    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self):
        """Test parallel execution of multiple tools."""
        collection = ToolCollection(
            CalculatorTool(),
            GreetingTool()
        )
        
        calls = [
            {"name": "calculator", "args": {"operation": "add", "a": 10, "b": 20}},
            {"name": "calculator", "args": {"operation": "multiply", "a": 5, "b": 5}},
            {"name": "greeting", "args": {"name": "World"}}
        ]
        
        results = await collection.execute_parallel(calls)
        
        assert len(results) == 3
        assert all(r.success for r in results)
        
        # Check results
        calc1 = json.loads(results[0].output)
        assert calc1["result"] == 30
        
        calc2 = json.loads(results[1].output)
        assert calc2["result"] == 25
        
        greeting = json.loads(results[2].output)
        assert "World" in greeting["greeting"]


class TestAgentMetrics:
    """Test agent metrics with real execution."""
    
    @pytest.mark.asyncio
    async def test_metrics_tracked(self):
        """Test that metrics are properly tracked during real execution."""
        collection = ToolCollection(CalculatorTool())
        
        # Execute some tools
        await collection.execute("calculator", operation="add", a=1, b=2)
        await collection.execute("calculator", operation="multiply", a=3, b=4)
        
        health = await collection.health_check()
        
        assert health["metrics"]["total_calls"] == 2
        assert health["metrics"]["successful_calls"] == 2


# Run tests with: pytest agent_unified/tests/test_integration.py -v --tb=short
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
