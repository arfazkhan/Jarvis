"""
Tests for ARVIS Agent System (Production-Ready)
================================================

Tests for:
- ARVISBaseAgent (state management, execution loop)
- ARVISReActAgent (think/act pattern)
- ARVISToolAgent (tool execution, tracing)
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent_unified.schema import AgentState, Message
from agent_unified.agents.base import ARVISBaseAgent
from agent_unified.agents.react import ARVISReActAgent
from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.tools.collection import ToolCollection


# Mock LLM response class
class MockLLMResponse:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = json.dumps(arguments)


# Test tools
class SimpleTool(BaseTool):
    name: str = "simple_tool"
    description: str = "A simple test tool"
    parameters: dict = {
        "type": "object",
        "properties": {
            "input": {"type": "string"}
        },
        "required": ["input"]
    }
    
    async def execute(self, input: str) -> ToolResult:
        return self.success_response({"output": f"Processed: {input}"})


class TerminateTool(BaseTool):
    name: str = "terminate"
    description: str = "Terminate agent execution"
    parameters: dict = {"type": "object", "properties": {}}
    
    async def execute(self) -> ToolResult:
        return self.success_response({"status": "terminated"})


# Concrete implementation of ARVISReActAgent for testing
class TestableReActAgent(ARVISReActAgent):
    """Testable ReAct agent with controllable think/act."""
    
    _think_returns: list = []
    _act_returns: list = []
    _think_count: int = 0
    _act_count: int = 0
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._think_returns = []
        self._act_returns = []
        self._think_count = 0
        self._act_count = 0
    
    def set_think_returns(self, values: list):
        self._think_returns = values
    
    def set_act_returns(self, values: list):
        self._act_returns = values
    
    async def think(self) -> bool:
        if self._think_count < len(self._think_returns):
            result = self._think_returns[self._think_count]
        else:
            result = False
        self._think_count += 1
        return result
    
    async def act(self) -> str:
        if self._act_count < len(self._act_returns):
            result = self._act_returns[self._act_count]
        else:
            result = "No action"
        self._act_count += 1
        return result


class TestARVISBaseAgent:
    """Tests for ARVISBaseAgent."""
    
    def test_initial_state(self):
        agent = TestableReActAgent(name="test_agent")
        
        assert agent.state == AgentState.IDLE
        assert agent.current_step == 0
        assert len(agent.memory.messages) == 0
    
    def test_update_memory(self):
        agent = TestableReActAgent(name="test_agent")
        
        agent.update_memory("user", "Hello")
        agent.update_memory("assistant", "Hi there!")
        
        assert len(agent.memory.messages) == 2
        assert agent.memory.messages[0].role == "user"
        assert agent.memory.messages[1].role == "assistant"
    
    @pytest.mark.asyncio
    async def test_run_with_request(self):
        agent = TestableReActAgent(name="test_agent")
        agent.set_think_returns([True, False])  # Think once, then done
        agent.set_act_returns(["Action completed"])
        
        result = await agent.run("Test request")
        
        # Request should be added to memory
        assert any("Test request" in str(m.content) for m in agent.memory.messages)
        assert agent.current_step >= 1
    
    @pytest.mark.asyncio
    async def test_max_steps_limit(self):
        agent = TestableReActAgent(name="test_agent", max_steps=3)
        # Always return True for think to force hitting max steps
        agent.set_think_returns([True, True, True, True, True])
        agent.set_act_returns(["act1", "act2", "act3", "act4", "act5"])
        
        result = await agent.run("Long task")
        
        # Should stop at or before max_steps
        assert agent.current_step <= agent.max_steps + 1
    
    @pytest.mark.asyncio
    async def test_state_transitions(self):
        agent = TestableReActAgent(name="test_agent")
        agent.set_think_returns([True, False])
        agent.set_act_returns(["done"])
        
        assert agent.state == AgentState.IDLE
        
        await agent.run("Test")
        
        # After run, should be finished
        assert agent.state in [AgentState.FINISHED, AgentState.IDLE]


class TestARVISToolAgent:
    """Tests for ARVISToolAgent."""
    
    @pytest.fixture
    def agent_with_tools(self):
        """Create agent with test tools."""
        agent = ARVISToolAgent(
            name="test_tool_agent",
            available_tools=ToolCollection(SimpleTool(), TerminateTool())
        )
        return agent
    
    @pytest.mark.asyncio
    async def test_tool_execution(self, agent_with_tools):
        # Directly test tool execution
        result = await agent_with_tools.available_tools.execute(
            "simple_tool", 
            input="test"
        )
        
        assert result.success
        data = json.loads(result.output)
        assert "Processed: test" in data["output"]
    
    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self, agent_with_tools):
        calls = [
            {"name": "simple_tool", "args": {"input": "a"}},
            {"name": "simple_tool", "args": {"input": "b"}},
        ]
        
        results = await agent_with_tools.available_tools.execute_parallel(calls)
        
        assert len(results) == 2
        assert all(r.success for r in results)
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, agent_with_tools):
        # Execute some tools
        await agent_with_tools.available_tools.execute("simple_tool", input="test1")
        await agent_with_tools.available_tools.execute("simple_tool", input="test2")
        
        health = await agent_with_tools.available_tools.health_check()
        
        assert health["metrics"]["total_calls"] == 2
        assert health["metrics"]["successful_calls"] == 2
    
    @pytest.mark.asyncio
    async def test_execution_traces(self, agent_with_tools):
        # The traces are populated during think/act cycle
        # Here we just verify the trace list exists
        assert isinstance(agent_with_tools.execution_traces, list)
    
    @pytest.mark.asyncio
    async def test_health_check(self, agent_with_tools):
        health = await agent_with_tools.health_check()
        
        assert "agent" in health
        assert "state" in health
        assert "tools" in health
        assert health["agent"] == "test_tool_agent"
    
    @pytest.mark.asyncio
    async def test_cleanup(self, agent_with_tools):
        # Should not raise
        await agent_with_tools.cleanup()
        assert True


class TestThinkActCycle:
    """Tests for think/act execution cycle with mocked LLM."""
    
    @pytest.mark.asyncio
    async def test_think_generates_tool_calls(self):
        agent = ARVISToolAgent(
            name="test_agent",
            available_tools=ToolCollection(SimpleTool())
        )
        
        # Mock LLM response with tool calls
        mock_response = MockLLMResponse(
            content="I'll use the simple tool",
            tool_calls=[MockToolCall("call1", "simple_tool", {"input": "test"})]
        )
        
        with patch.object(agent.llm, 'ask_tool', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            
            result = await agent.think()
            
            assert result is True
            assert len(agent.tool_calls) == 1
            assert agent.tool_calls[0].function.name == "simple_tool"
    
    @pytest.mark.asyncio
    async def test_act_executes_tools(self):
        agent = ARVISToolAgent(
            name="test_agent",
            available_tools=ToolCollection(SimpleTool())
        )
        
        # Manually set tool calls
        from agent_unified.schema import ToolCall, Function
        agent.tool_calls = [
            ToolCall(
                id="call1",
                function=Function(name="simple_tool", arguments='{"input": "test"}')
            )
        ]
        
        result = await agent.act()
        
        assert "simple_tool" in result
        assert agent.tool_calls == []  # Cleared after execution


class TestAgentResilience:
    """Tests for agent resilience to errors."""
    
    @pytest.mark.asyncio
    async def test_invalid_tool_name(self):
        agent = ARVISToolAgent(
            name="test_agent",
            available_tools=ToolCollection(SimpleTool())
        )
        
        result = await agent.available_tools.execute("nonexistent_tool")
        
        assert not result.success
        assert "not found" in result.error
    
    @pytest.mark.asyncio
    async def test_tool_with_invalid_args(self):
        agent = ARVISToolAgent(
            name="test_agent",
            available_tools=ToolCollection(SimpleTool())
        )
        
        # Missing required parameter
        result = await agent.available_tools.execute("simple_tool")
        
        assert not result.success
        assert "Missing required" in result.error


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
