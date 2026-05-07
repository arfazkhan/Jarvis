"""
Stress Test: Alarm Flood
=========================

Test ARVIS behavior when flooded with alarms.
- 500 alarms in 10 seconds
- System should not crash
- Memory should not explode
"""

import pytest
import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any

from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.bms_state_engine import BMSStateEngine
from tests.factories import AlarmFactory, EquipmentFactory
from tests.mocks import MockBMSStateEngine


class TestAlarmFlood:
    """What happens when 500 alarms arrive in 10 seconds?"""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_alarm_flood_500_in_10s(self, mock_bms_state):
        """Generate 500 alarms, verify system doesn't crash."""
        # Setup
        alarm_engine = AlarmEngine(state_engine=mock_bms_state)
        
        # Add equipment
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        for i in range(5):
            mock_bms_state.add_equipment(EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}"))
        
        # Generate 500 alarms
        alarms = []
        for i in range(500):
            alarms.append(AlarmFactory.critical_chiller(alarm_id=f"ALM-{i:04d}"))
        
        # Process all
        start = time.time()
        for alarm in alarms:
            mock_bms_state.add_alarm(alarm)
        
        # Cluster alarms
        active_alarms = mock_bms_state.get_active_alarms()
        clusters = alarm_engine.cluster_alarms(active_alarms)
        elapsed = time.time() - start
        
        # Verify
        assert elapsed < 5.0, f"Should process 500 alarms in under 5 seconds (took {elapsed:.2f}s)"
        assert len(clusters) > 0, "Should cluster alarms"
        assert len(active_alarms) == 500, "Should have 500 active alarms"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_alarm_flood_1000_alarms(self, mock_bms_state):
        """1000 alarms should still be processed reasonably."""
        alarm_engine = AlarmEngine(state_engine=mock_bms_state)
        
        # Add equipment
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Generate 1000 alarms
        alarms = [AlarmFactory.random(alarm_id=f"ALM-{i:05d}") for i in range(1000)]
        
        # Process
        start = time.time()
        for alarm in alarms:
            mock_bms_state.add_alarm(alarm)
        
        active_alarms = mock_bms_state.get_active_alarms()
        clusters = alarm_engine.cluster_alarms(active_alarms)
        elapsed = time.time() - start
        
        # Verify
        assert elapsed < 10.0, f"Should process 1000 alarms in under 10 seconds (took {elapsed:.2f}s)"
        assert len(active_alarms) == 1000
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_alarm_acknowledgment_stress(self, mock_bms_state):
        """Acknowledge 500 alarms rapidly."""
        alarm_engine = AlarmEngine(state_engine=mock_bms_state)
        
        # Add 500 alarms
        for i in range(500):
            alarm = AlarmFactory.critical_chiller(alarm_id=f"ALM-{i:04d}")
            mock_bms_state.add_alarm(alarm)
        
        # Acknowledge all rapidly
        start = time.time()
        acknowledged = 0
        for alarm in mock_bms_state._alarms:
            if mock_bms_state.acknowledge_alarm(alarm["alarm_id"]):
                acknowledged += 1
        elapsed = time.time() - start
        
        # Verify
        assert acknowledged == 500, f"Should acknowledge all 500 alarms"
        assert elapsed < 2.0, f"Should acknowledge 500 alarms in under 2 seconds (took {elapsed:.2f}s)"
        assert len(mock_bms_state.get_active_alarms()) == 0, "Should have no active alarms"


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
