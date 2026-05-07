"""
Integration Test: Alarm Cascade Response
==========================================

Real-world scenario: Chiller trips → 5 zone alarms.

Tests the full flow:
1. BMS publishes 6 alarm events
2. AlarmEngine clusters into cascade
3. Root cause identified as CH-01
4. Operator asks "what happened?"
5. BMSLLMAgent explains cascade
"""

import pytest
import json
import asyncio
from datetime import datetime

from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.bms_state_engine import BMSStateEngine

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import AlarmFactory, EquipmentFactory


class TestAlarmCascadeResponse:
    """Test alarm cascade detection and response."""
    
    @pytest.fixture
    def state_engine(self):
        """Real BMSStateEngine with sample equipment."""
        state = BMSStateEngine()
        state.register_equipment(EquipmentFactory.chiller())
        for i in range(1, 6):
            state.register_equipment(EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}"))
        return state
    
    @pytest.fixture
    def alarm_engine(self, state_engine):
        """Real AlarmEngine with real state."""
        return AlarmEngine(state_engine=state_engine)
    
    @pytest.mark.asyncio
    async def test_chiller_trip_creates_cascade(self, alarm_engine, state_engine):
        """Chiller trip should create alarm cascade."""
        # Generate cascade: 1 chiller alarm + 5 zone alarms
        cascade_alarms = AlarmFactory.cascade(count=6, root_equipment="CH-01")
        
        # Add alarms to state
        for alarm in cascade_alarms:
            state_engine.add_alarm(alarm)
        
        # Execute clustering
        clusters = alarm_engine.cluster_alarms(state_engine.get_active_alarms())
        
        # Verify
        assert len(clusters) == 1, "Should cluster into single cascade"
        cluster = clusters[0]
        assert len(cluster.alarm_ids) == 6, "Should include all 6 alarms"
        assert cluster.root_cause_equipment_id == "CH-01", "Root cause should be chiller"
        assert cluster.root_cause_confidence > 0.7, "Should be confident in root cause"
    
    @pytest.mark.asyncio
    async def test_multiple_cascades_detected(self, alarm_engine, state_engine):
        """Multiple independent cascades should be detected."""
        # Cascade 1: Chiller 1
        cascade1 = AlarmFactory.cascade(count=3, root_equipment="CH-01")
        # Cascade 2: AHU 1
        cascade2 = AlarmFactory.cascade(count=2, root_equipment="AHU-01")
        
        all_alarms = cascade1 + cascade2
        for alarm in all_alarms:
            state_engine.add_alarm(alarm)
        
        clusters = alarm_engine.cluster_alarms(state_engine.get_active_alarms())
        
        assert len(clusters) == 2, "Should detect 2 independent cascades"
    
    @pytest.mark.asyncio
    async def test_cascade_explanation_via_llm(self, mock_llm):
        """LLM should explain cascade in human terms."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        from agent_commercial.bms_state_engine import BMSStateEngine
        
        # Setup LLM to return explanation
        mock_llm.responses["cascade"] = json.dumps({
            "explanation": "Chiller 1 tripped due to high vibration, causing 5 zone alarms",
            "root_cause": "CH-01 bearing wear",
            "affected_zones": ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"],
            "recommended_action": "Schedule CH-01 maintenance within 48 hours"
        })
        
        state = BMSStateEngine()
        agent = BMSLLMAgent(bms_state=state, llm=mock_llm)
        
        # Ask about cascade
        response = await agent.ask("What happened with the alarms?")
        
        # Verify
        assert "CH-01" in response or "chiller" in response.lower()
        assert mock_llm.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_alarm_priority_ordering(self, alarm_engine, state_engine):
        """Alarms should be ordered by priority (safety > comfort > energy)."""
        # Add alarms of different severities
        alarms = [
            AlarmFactory.critical_chiller(),
            AlarmFactory.warning_ahu(),
            AlarmFactory.info_zone(),
        ]
        
        for alarm in alarms:
            state_engine.add_alarm(alarm)
        
        active = state_engine.get_active_alarms()
        
        # Verify ordering
        assert active[0]["severity"] == "critical"
        assert active[-1]["severity"] in ["info", "low"]
    
    @pytest.mark.asyncio
    async def test_alarm_acknowledgment_flow(self, alarm_engine, state_engine):
        """Alarm acknowledgment should update state."""
        alarm = AlarmFactory.critical_chiller()
        state_engine.add_alarm(alarm)
        
        # Acknowledge
        success = state_engine.acknowledge_alarm(alarm["alarm_id"], "Test operator")
        
        assert success
        # Acknowledged alarms should not appear in active
        active = state_engine.get_active_alarms()
        assert alarm["alarm_id"] not in [a["alarm_id"] for a in active]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
