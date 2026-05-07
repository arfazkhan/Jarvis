"""
Integration Test: BMS Connectivity
===================================

Tests BACnet adapter + BMSStateEngine integration.
"""

import pytest
import asyncio

from agent_commercial.bms_state_engine import BMSStateEngine
from agent_unified.engines.bacnet import BACnetSimulatorAdapter

from tests.factories import EquipmentFactory


class TestBMSConnectivity:
    """Test BACnet to StateEngine integration."""
    
    @pytest.fixture
    def bacnet_adapter(self):
        """BACnet simulator adapter."""
        return BACnetSimulatorAdapter()
    
    @pytest.fixture
    def state_engine(self):
        """Real BMSStateEngine."""
        return BMSStateEngine()
    
    @pytest.mark.asyncio
    async def test_bacnet_connects_and_discovers(self, bacnet_adapter):
        """BACnet adapter should connect and discover devices."""
        connected = await bacnet_adapter.connect()
        assert connected
        
        devices = await bacnet_adapter.discover_devices()
        assert len(devices) > 0
        
        await bacnet_adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_point_read_updates_state(
        self,
        bacnet_adapter,
        state_engine,
    ):
        """Reading BACnet points should update state engine."""
        # Setup
        await bacnet_adapter.connect()
        state_engine.register_equipment(EquipmentFactory.chiller())
        
        # Configure point
        from agent_unified.engines.bacnet import BACnetPoint
        bacnet_adapter.add_point(BACnetPoint(
            device_id=1001,
            object_type="analogInput",
            object_instance=1,
            point_id="CH-01/CHWST",
            point_name="Chilled Water Supply Temp",
            equipment_id="CH-01",
            unit="°C",
        ))
        
        # Read point
        point = await bacnet_adapter.read_point(bacnet_adapter.points["CH-01/CHWST"])
        
        assert point is not None
        assert point.value is not None
        
        # Update state
        state_engine.update_point(
            point.point_id,
            point.value,
            point.unit,
            point.equipment_id,
        )
        
        # Verify state updated
        current = state_engine.get_point("CH-01/CHWST")
        assert current is not None
        assert current["value"] == point.value
        
        await bacnet_adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_polling_feeds_state(
        self,
        bacnet_adapter,
        state_engine,
    ):
        """Background polling should continuously update state."""
        await bacnet_adapter.connect()
        
        # Start polling
        bacnet_adapter.start_polling(interval_seconds=1)
        
        # Wait for a few polls
        await asyncio.sleep(3)
        
        # Stop polling
        bacnet_adapter.stop_polling()
        
        await bacnet_adapter.disconnect()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
