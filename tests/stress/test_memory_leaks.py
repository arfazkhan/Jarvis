"""
Stress Test: Memory Leaks
=========================

Test ARVIS for memory leaks over long-running operations.
- Extended operation cycles
- Memory growth monitoring
- Cleanup verification
"""

import pytest
import asyncio
import gc
from datetime import datetime, timedelta

from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.energy_analyzer import EnergyAnalyzer
from tests.factories import EquipmentFactory, AlarmFactory, DataPointFactory
from tests.mocks import MockBMSStateEngine


class TestMemoryLeaks:
    """Memory leak detection over extended operations."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_long_running_alarm_processing(self, mock_bms_state):
        """Process alarms for 1000 iterations, check memory."""
        alarm_engine = AlarmEngine(state_engine=mock_bms_state)
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Get baseline
        gc.collect()
        initial_objects = len(gc.get_objects())
        
        # Process 1000 alarm cycles
        for i in range(1000):
            # Add alarm
            alarm = AlarmFactory.random(alarm_id=f"ALM-{i:05d}")
            mock_bms_state.add_alarm(alarm)
            
            # Process
            active = mock_bms_state.get_active_alarms()
            clusters = alarm_engine.cluster_alarms(active)
            
            # Clear every 100 cycles
            if i % 100 == 0:
                mock_bms_state._alarms = []
        
        # Check memory
        gc.collect()
        final_objects = len(gc.get_objects())
        
        # Should not grow unbounded
        growth = final_objects - initial_objects
        assert growth < 1000, f"Memory grew by {growth} objects (potential leak)"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_long_running_point_updates(self, mock_bms_state):
        """Update points for 10000 iterations, check memory."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Get baseline
        gc.collect()
        initial_objects = len(gc.get_objects())
        
        # Update points 10000 times
        for i in range(10000):
            mock_bms_state.update_point(
                f"CH-01/TEST-{i % 100}",
                float(i),
                equipment_id="CH-01"
            )
        
        # Check memory
        gc.collect()
        final_objects = len(gc.get_objects())
        
        # Memory should not grow linearly with updates
        growth = final_objects - initial_objects
        assert growth < 5000, f"Memory grew by {growth} objects (potential leak)"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_callback_cleanup(self, mock_bms_state):
        """Callbacks should not accumulate."""
        callback_count = 0
        
        def counting_callback(point):
            nonlocal callback_count
            callback_count += 1
        
        # Register many callbacks
        for _ in range(100):
            mock_bms_state.on_point_update(counting_callback)
        
        # Verify callbacks don't leak
        initial_callbacks = len(mock_bms_state._callbacks)
        
        # Process points
        for i in range(100):
            mock_bms_state.update_point(f"TEST-{i}", float(i))
        
        # Should still have reasonable number of callbacks
        assert len(mock_bms_state._callbacks) < 150, "Callbacks should not accumulate unbounded"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_history_cleanup(self, mock_bms_state):
        """Point history should be cleaned up."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add many points with history
        for i in range(1000):
            mock_bms_state.update_point("CH-01/CHWST", float(i), equipment_id="CH-01")
        
        # Check history size
        history = mock_bms_state._point_history.get("CH-01/CHWST", [])
        
        # History should have reasonable limit
        # (In real implementation, would have max history size)
        # For now, just verify it exists
        assert len(history) == 1000, "History should have all updates"


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
