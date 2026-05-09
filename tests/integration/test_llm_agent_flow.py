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
        return BMSStateEngine()
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM with tool responses."""
        return MockLLM()
    
    
    @pytest.mark.asyncio
    async def test_agent_handles_equipment_query(self, mock_llm, bms_state):
        """Agent should handle equipment status query."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        llm_agent = BMSLLMAgent(bms_state=bms_state, llm=mock_llm)
        from agent_commercial.bms_data_model import Equipment, EquipmentType
        await bms_state.register_equipment(Equipment(
            equipment_id="CH-01",
            name="Chiller 1",
            equipment_type=EquipmentType.CHILLER
        ))
        
        # Setup LLM response
        mock_llm.responses["equipment"] = json.dumps({
            "tool": "get_equipment_status",
            "arguments": {"equipment_id": "CH-01"},
        })
        
        response = await llm_agent.chat("What is the status of Chiller 1?")
        
        assert response.text is not None
        assert mock_llm.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_agent_handles_alarm_query(self, mock_llm, bms_state):
        """Agent should handle alarm queries."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        llm_agent = BMSLLMAgent(bms_state=bms_state, llm=mock_llm)
        from tests.factories import AlarmFactory
        
        from agent_commercial.bms_data_model import Equipment, EquipmentType
        await bms_state.register_equipment(Equipment(
            equipment_id="CH-01",
            name="Chiller 1",
            equipment_type=EquipmentType.CHILLER
        ))
        
        # Add alarm
        from agent_commercial.bms_data_model import Alarm, AlarmSeverity, AlarmState
        alarm_dict = AlarmFactory.critical_chiller()
        
        # Map factory 'status' to model 'state'
        if "status" in alarm_dict:
            status_val = alarm_dict.pop("status")
            try:
                alarm_dict["state"] = AlarmState(status_val)
            except ValueError:
                alarm_dict["state"] = AlarmState.ACTIVE
        
        # Map factory 'timestamp' to model 'triggered_at'
        if "timestamp" in alarm_dict:
            ts_str = alarm_dict.pop("timestamp")
            from datetime import datetime
            try:
                alarm_dict["triggered_at"] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                alarm_dict["triggered_at"] = datetime.now()
                
        # Remove any other keys not in Alarm dataclass
        import dataclasses
        alarm_fields = {f.name for f in dataclasses.fields(Alarm)}
        filtered_dict = {k: v for k, v in alarm_dict.items() if k in alarm_fields}
        
        alarm = Alarm(**filtered_dict)
        # Ensure severity is an enum if it's still a string
        if isinstance(alarm.severity, str):
            try:
                alarm.severity = AlarmSeverity(alarm.severity)
            except ValueError:
                alarm.severity = AlarmSeverity.MEDIUM
            
        await bms_state.add_alarm(alarm)
        
        # Setup LLM response
        mock_llm.responses["alarm"] = json.dumps({
            "tool": "get_active_alarms",
            "arguments": {},
        })
        
        response = await llm_agent.chat("Are there any active alarms?")
        
        assert response.text is not None
    
    @pytest.mark.asyncio
    async def test_agent_handles_natural_language(self, mock_llm, bms_state):
        """Agent should handle natural language queries."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        llm_agent = BMSLLMAgent(bms_state=bms_state, llm=mock_llm)
        from agent_commercial.bms_data_model import Equipment, EquipmentType
        await bms_state.register_equipment(Equipment(
            equipment_id="CH-01",
            name="Chiller 1",
            equipment_type=EquipmentType.CHILLER
        ))
        
        mock_llm.responses["natural"] = json.dumps({
            "response": "All systems are operating normally",
        })
        
        response = await llm_agent.chat("How is everything running?")
        
        assert response.text is not None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
