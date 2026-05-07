"""
Stress Test: Malformed Data
============================

Test ARVIS behavior with garbage input.
- Malformed BACnet responses
- Invalid JSON
- Wrong data types
- Missing fields
"""

import pytest
import asyncio
from typing import Any, Dict

from agent_commercial.tools.equipment_tools import GetEquipmentStatus
from agent_commercial.bms_state_engine import BMSStateEngine
from tests.factories import EquipmentFactory
from tests.mocks import MockBMSStateEngine, MockBACnetAdapter


class TestMalformedData:
    """How does ARVIS handle garbage input?"""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_bacnet_returns_error_string(self, mock_bms_state):
        """BACnet returned 'ERROR' string instead of float."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add point with garbage value
        mock_bms_state.update_point("CH-01/GARBAGE", "ERROR", equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
        # Should not crash
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_bacnet_returns_none(self, mock_bms_state):
        """BACnet returned None."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add point with None value
        mock_bms_state.update_point("CH-01/NONE", None, equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_bacnet_returns_infinity(self, mock_bms_state):
        """BACnet returned infinity or NaN."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add points with special float values
        mock_bms_state.update_point("CH-01/INF", float('inf'), equipment_id="CH-01")
        mock_bms_state.update_point("CH-01/NAN", float('nan'), equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_equipment_missing_required_fields(self, mock_bms_state):
        """Equipment dict missing required fields."""
        # Add equipment with missing fields
        mock_bms_state.add_equipment({
            "equipment_id": "BROKEN-01",
            # Missing 'name', 'type', etc.
        })
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="BROKEN-01")
        
        # Should handle gracefully
        assert result.success or result.error
        if result.success:
            # Should still return something
            assert "equipment" in result.output or "data" in result.output
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_alarm_with_missing_fields(self, mock_bms_state):
        """Alarm missing required fields."""
        # Add alarm with missing fields
        mock_bms_state.add_alarm({
            # Missing 'alarm_id', 'severity', etc.
            "message": "Something broke"
        })
        
        # System should not crash when processing alarms
        alarms = mock_bms_state.get_active_alarms()
        assert len(alarms) >= 0  # Should return something or empty list
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_malformed_json_in_point_value(self, mock_bms_state):
        """Point value is JSON string instead of number."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add point with JSON string value
        mock_bms_state.update_point(
            "CH-01/JSON",
            '{"broken": true}',
            equipment_id="CH-01"
        )
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_bacnet_returns_list_instead_of_float(self, mock_bms_state):
        """BACnet returned list instead of single value."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add point with list value
        mock_bms_state.update_point("CH-01/LIST", [1, 2, 3], equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_bacnet_returns_negative_temp(self, mock_bms_state):
        """BACnet returned negative temperature (impossible in cooling)."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add point with impossible value
        mock_bms_state.update_point("CH-01/CHWST", -50.0, equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should return value but might flag as anomaly
        assert result.success or result.error


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
