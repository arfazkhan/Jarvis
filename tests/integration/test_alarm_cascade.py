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
import dataclasses
from datetime import datetime

from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.bms_data_model import Alarm, AlarmSeverity, AlarmState, Equipment, EquipmentType

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import AlarmFactory, EquipmentFactory


class TestAlarmCascadeResponse:
    """Test alarm cascade detection and response."""
    
    async def get_state_engine(self):
        """Helper to create state engine with equipment and relationships matching AlarmFactory.cascade."""
        state = BMSStateEngine()
        
        # Chiller 1
        chiller = Equipment(
            equipment_id="CH-01",
            name="Chiller 1",
            equipment_type=EquipmentType.CHILLER,
            child_equipment_ids=[f"VAV-{i:02d}" for i in range(10)]
        )
        await state.register_equipment(chiller)
        
        # VAVs linked to Chiller 1 (matching AlarmFactory.cascade)
        for i in range(10):
            vav = Equipment(
                equipment_id=f"VAV-{i:02d}",
                name=f"VAV {i}",
                equipment_type=EquipmentType.VAV,
                parent_equipment_id="CH-01"
            )
            await state.register_equipment(vav)
            
        return state

    @pytest.fixture
    def alarm_engine(self):
        """Real AlarmEngine."""
        return AlarmEngine()

    def _create_alarm(self, alarm_dict: dict) -> Alarm:
        """Helper to create Alarm object from factory dict."""
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
            try:
                alarm_dict["triggered_at"] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                alarm_dict["triggered_at"] = datetime.now()
        else:
            alarm_dict["triggered_at"] = datetime.now()
                
        # Remove any other keys not in Alarm dataclass
        alarm_fields = {f.name for f in dataclasses.fields(Alarm)}
        filtered_dict = {k: v for k, v in alarm_dict.items() if k in alarm_fields}
        
        alarm = Alarm(**filtered_dict)
        # Ensure severity is an enum
        if isinstance(alarm.severity, str):
            try:
                alarm.severity = AlarmSeverity(alarm.severity)
            except ValueError:
                alarm.severity = AlarmSeverity.MEDIUM
        return alarm

    @pytest.mark.asyncio
    async def test_chiller_trip_creates_cascade(self, alarm_engine, mock_llm):
        """Chiller trip should create alarm cascade."""
        state_engine = await self.get_state_engine()
        alarm_engine.llm_provider = mock_llm
        
        # Generate cascade: 1 chiller alarm + 5 zone alarms
        cascade_dicts = AlarmFactory.cascade(count=6, root_equipment="CH-01")
        
        # Load topology into engine
        active_equipment = list(state_engine._equipment.values())
        alarm_engine.set_equipment_topology(active_equipment)
        
        # Ingest alarms into engine and add to state
        now = datetime.now()
        for i, d in enumerate(cascade_dicts):
            d["timestamp"] = now.isoformat()
            alarm = self._create_alarm(d)
            await state_engine.add_alarm(alarm)
            await alarm_engine.ingest_alarm(alarm)
        
        # Get clusters from engine
        clusters = alarm_engine.get_clusters()
        
        # Verify
        assert len(clusters) >= 1, f"Should cluster into at least one cascade, found {len(clusters)}"
        # Check if any cluster has our chiller as root cause
        chiller_clusters = [c for c in clusters if c.root_cause_equipment_id == "CH-01"]
        assert len(chiller_clusters) > 0, "Should find a cluster with CH-01 as root cause"
    
    @pytest.mark.asyncio
    async def test_multiple_cascades_detected(self, alarm_engine, mock_llm):
        """Multiple independent cascades should be detected."""
        state_engine = await self.get_state_engine()
        alarm_engine.llm_provider = mock_llm
        
        # Load topology
        active_equipment = list(state_engine._equipment.values())
        alarm_engine.set_equipment_topology(active_equipment)
        
        # Cascade 1: Chiller 1
        cascade1_dicts = AlarmFactory.cascade(count=3, root_equipment="CH-01")
        
        # Cascade 2: AHU-01 (Need to register its children to make it a cascade root)
        # Actually AHU-01 has CH-01 as parent, so it's related to CH-01.
        # To make it INDEPENDENT, maybe use a different system?
        # Let's just use two unrelated equipment.
        
        await state_engine.register_equipment(Equipment(
            equipment_id="GEN-01",
            name="Generator 1",
            equipment_type=EquipmentType.OTHER,
            child_equipment_ids=["ATS-01"]
        ))
        await state_engine.register_equipment(Equipment(
            equipment_id="ATS-01",
            name="ATS 1",
            equipment_type=EquipmentType.OTHER,
            parent_equipment_id="GEN-01"
        ))
        
        # Reload topology
        active_equipment = list(state_engine._equipment.values())
        alarm_engine.set_equipment_topology(active_equipment)
        
        # Cascade 2: Generator
        cascade2_dicts = [
            AlarmFactory.critical_chiller(equipment_id="GEN-01", message="Generator Fail"),
            AlarmFactory.warning_ahu(equipment_id="ATS-01", message="ATS on Battery")
        ]
        
        now = datetime.now()
        for d in cascade1_dicts:
            d["timestamp"] = now.isoformat()
            alarm = self._create_alarm(d)
            await state_engine.add_alarm(alarm)
            await alarm_engine.ingest_alarm(alarm)
            
        for d in cascade2_dicts:
            d["timestamp"] = now.isoformat()
            alarm = self._create_alarm(d)
            await state_engine.add_alarm(alarm)
            await alarm_engine.ingest_alarm(alarm)
        
        clusters = alarm_engine.get_clusters()
        
        assert len(clusters) >= 2, f"Should detect at least 2 independent cascades, found {len(clusters)}"
    
    @pytest.mark.asyncio
    async def test_cascade_explanation_via_llm(self, mock_llm):
        """LLM should explain cascade in human terms."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        from agent_commercial.bms_state_engine import BMSStateEngine
        
        # Setup LLM to return explanation
        mock_llm.responses["alarm"] = "Chiller 1 tripped due to high vibration, causing 5 zone alarms. Root cause is CH-01 bearing wear."
        
        state = BMSStateEngine()
        agent = BMSLLMAgent(bms_state=state, llm=mock_llm)
        
        # Ask about cascade
        response = await agent.chat("What happened with the alarms?")
        
        # Verify
        assert "CH-01" in response.text or "chiller" in response.text.lower()
        assert mock_llm.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_alarm_priority_ordering(self, alarm_engine):
        """Alarms should be ordered by priority (critical > warning > info)."""
        state_engine = await self.get_state_engine()
        
        # Add alarms of different severities
        critical = self._create_alarm(AlarmFactory.critical_chiller())
        warning = self._create_alarm(AlarmFactory.warning_ahu())
        info = self._create_alarm(AlarmFactory.info_zone())
        
        await state_engine.add_alarm(critical)
        await state_engine.add_alarm(warning)
        await state_engine.add_alarm(info)
        
        await alarm_engine.ingest_alarm(critical)
        await alarm_engine.ingest_alarm(warning)
        await alarm_engine.ingest_alarm(info)
        
        active = await state_engine.get_active_alarms()
        
        # Verify presence
        severities = [a.severity for a in active]
        assert AlarmSeverity.CRITICAL in severities
        assert AlarmSeverity.INFO in severities
        
        # Verify engine ranking
        queue = alarm_engine.get_priority_queue()
        assert queue[0].alarm.severity == AlarmSeverity.CRITICAL
    
    @pytest.mark.asyncio
    async def test_alarm_acknowledgment_flow(self, alarm_engine):
        """Alarm acknowledgment should update state."""
        state_engine = await self.get_state_engine()
        alarm_obj = self._create_alarm(AlarmFactory.critical_chiller())
        await state_engine.add_alarm(alarm_obj)
        
        # Acknowledge
        success = await state_engine.acknowledge_alarm(alarm_obj.alarm_id, "Test operator")
        
        assert success
        # Acknowledged alarms should still appear in active but with state ACKNOWLEDGED
        active = await state_engine.get_active_alarms()
        matches = [a for a in active if a.alarm_id == alarm_obj.alarm_id]
        assert len(matches) == 1
        assert matches[0].state == AlarmState.ACKNOWLEDGED


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
