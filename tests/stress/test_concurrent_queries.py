"""
Stress Test: Concurrent Queries
================================

Test ARVIS behavior under concurrent load.
- 100 concurrent tool calls
- No race conditions
- No data corruption
"""

import pytest
import asyncio
from typing import List

from agent_commercial.tools.equipment_tools import GetEquipmentStatus
from agent_commercial.tools.alarm_tools import GetActiveAlarms
from agent_commercial.tools.energy_tools import AnalyzeEnergy
from tests.factories import EquipmentFactory
from tests.mocks import MockBMSStateEngine


class TestConcurrentQueries:
    """What happens with 100 concurrent tool calls?"""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_concurrent_calls_same_equipment(self, mock_bms_state):
        """100 concurrent requests for same equipment."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Run 100 concurrent calls
        tasks = [
            tool.execute(equipment_id="CH-01")
            for _ in range(100)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
        
        # Verify all succeeded
        successes = [r for r in results if hasattr(r, 'success') and r.success]
        assert len(successes) == 100, f"Only {len(successes)} succeeded"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_concurrent_calls_different_equipment(self, mock_bms_state):
        """100 concurrent requests for different equipment."""
        # Add 100 different equipment
        for i in range(100):
            mock_bms_state.add_equipment(
                EquipmentFactory.chiller(equipment_id=f"CH-{i:03d}")
            )
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Run concurrent calls
        tasks = [
            tool.execute(equipment_id=f"CH-{i:03d}")
            for i in range(100)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all succeeded
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
        
        successes = [r for r in results if hasattr(r, 'success') and r.success]
        assert len(successes) == 100
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_concurrent_mixed_tools(self, mock_bms_state):
        """50 equipment calls + 50 alarm calls concurrently."""
        # Setup
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_equipment(EquipmentFactory.ahu())
        
        # Add some alarms
        from tests.factories import AlarmFactory
        for i in range(10):
            mock_bms_state.add_alarm(AlarmFactory.warning_ahu(alarm_id=f"ALM-{i}"))
        
        # Create tools
        equip_tool = GetEquipmentStatus()
        equip_tool.bms_state = mock_bms_state
        
        alarm_tool = GetActiveAlarms()
        alarm_tool.bms_state = mock_bms_state
        
        # Mix of calls
        tasks = []
        for i in range(50):
            tasks.append(equip_tool.execute(equipment_id="CH-01"))
            tasks.append(alarm_tool.execute())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_concurrent_writes_no_corruption(self, mock_bms_state):
        """Concurrent state updates should not corrupt data."""
        # Add equipment
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Concurrent updates to same point
        async def update_point(i):
            mock_bms_state.update_point("CH-01/CHWST", float(i), equipment_id="CH-01")
        
        tasks = [update_point(i) for i in range(100)]
        await asyncio.gather(*tasks)
        
        # Verify point exists (value will be one of the concurrent writes)
        point = mock_bms_state.get_point("CH-01/CHWST")
        assert point is not None, "Point should exist"
        assert "CHWST" in point["point_id"]


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
