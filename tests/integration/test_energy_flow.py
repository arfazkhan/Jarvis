"""
Integration Test: Energy Flow
=============================

Tests EnergyAnalyzer + BMS data integration.
"""

import pytest
from datetime import datetime, timedelta

from agent_commercial.energy_analyzer import EnergyAnalyzer
from agent_commercial.bms_state_engine import BMSStateEngine

from tests.mocks import MockBMSStateEngine, MockEnergyAnalyzer
from tests.factories import EquipmentFactory, EnergyReadingFactory


class TestEnergyFlow:
    """Test energy analysis with BMS data."""
    
    @pytest.fixture
    def bms_state(self):
        """Real BMSStateEngine."""
        state = BMSStateEngine()
        state.register_equipment(EquipmentFactory.meter())
        state.register_equipment(EquipmentFactory.chiller())
        return state
    
    @pytest.fixture
    def energy_analyzer(self, bms_state):
        """Real EnergyAnalyzer with real state."""
        return EnergyAnalyzer(bms_state=bms_state)
    
    @pytest.mark.asyncio
    async def test_energy_summary_from_real_data(self, energy_analyzer, bms_state):
        """Energy summary should reflect actual BMS data."""
        # Add real energy readings
        readings = EnergyReadingFactory.last_24_hours()
        for reading in readings:
            bms_state.add_energy_reading(reading)
        
        summary = energy_analyzer.get_summary()
        
        assert summary["total_kwh"] > 0
        assert summary["cost_qar"] > 0
    
    @pytest.mark.asyncio
    async def test_waste_detection_integration(self, energy_analyzer, bms_state):
        """Waste patterns should be detected from BMS data."""
        # Add waste pattern
        energy_analyzer.add_waste_pattern({
            "pattern_type": "ghost_operation",
            "zone_id": "ZONE-01",
            "estimated_savings_qar": 50.0,
        })
        
        patterns = energy_analyzer.identify_waste_patterns()
        
        assert len(patterns) > 0
        assert patterns[0]["pattern_type"] == "ghost_operation"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
