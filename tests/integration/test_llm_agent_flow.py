"""
Integration Test: LLM Agent Flow
=================================

Tests LLMAgent + Tools + StateEngine integration.
"""

import pytest
import json

from agent_commercial.bms_llm_agent import BMSLLMAgent
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.tools.handlers import BMSToolHandler

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import EquipmentFactory


class TestLLMAgentFlow:
    """Test LLM agent with real tools."""
    
    @pytest.fixture
    def bms_state(self):
        """Real BMSStateEngine."""
        state = BMSStateEngine()
        state.register_equipment(EquipmentFactory.chiller())
        state.register_equipment(EquipmentFactory.ahu())
        return state
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM with tool responses."""
        return MockLLM()
    
    @pytest.fixture
    def llm_agent(self, bms_state, mock_llm):
        """Real BMSLLMAgent."""
        return BMSLLMAgent(
            bms_state=bms_state,
            llm=mock_llm,
        )
    
    @pytest.mark.asyncio
    async def test_agent_handles_equipment_query(self, llm_agent, mock_llm):
        """Agent should handle equipment status query."""
        # Setup LLM response
        mock_llm.responses["equipment"] = json.dumps({
            "tool": "get_equipment_status",
            "arguments": {"equipment_id": "CH-01"},
        })
        
        response = await llm_agent.ask("What is the status of Chiller 1?")
        
        assert response is not None
        assert mock_llm.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_agent_handles_alarm_query(self, llm_agent, mock_llm, bms_state):
        """Agent should handle alarm queries."""
        from tests.factories import AlarmFactory
        
        # Add alarm
        alarm = AlarmFactory.critical_chiller()
        bms_state.add_alarm(alarm)
        
        # Setup LLM response
        mock_llm.responses["alarm"] = json.dumps({
            "tool": "get_active_alarms",
            "arguments": {},
        })
        
        response = await llm_agent.ask("Are there any active alarms?")
        
        assert response is not None
    
    @pytest.mark.asyncio
    async def test_agent_handles_natural_language(self, llm_agent, mock_llm):
        """Agent should handle natural language queries."""
        mock_llm.responses["natural"] = json.dumps({
            "response": "All systems are operating normally",
        })
        
        response = await llm_agent.ask("How is everything running?")
        
        assert response is not None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
