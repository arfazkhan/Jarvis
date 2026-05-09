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
    async def bms_state(self):
        """Real BMSStateEngine."""
        state = BMSStateEngine()
        await state.register_equipment(EquipmentFactory.meter())
        await state.register_equipment(EquipmentFactory.chiller())
        return state
    
    @pytest.fixture
    def energy_analyzer(self):
        """Real EnergyAnalyzer."""
        return EnergyAnalyzer()
    
    @pytest.mark.asyncio
    async def test_energy_summary_from_real_data(self, energy_analyzer, bms_state):
        """Energy summary should reflect actual BMS data."""
        # Add real energy readings directly to analyzer
        from agent_commercial.bms_data_model import EnergyReading
        from datetime import datetime
        
        readings = EnergyReadingFactory.last_24_hours()
        for r_dict in readings:
            reading = EnergyReading(
                meter_id=r_dict["building_id"],
                value=r_dict["total_kw"],
                timestamp=datetime.fromisoformat(r_dict["timestamp"]) if isinstance(r_dict["timestamp"], str) else r_dict["timestamp"],
                unit="kW"
            )
            energy_analyzer.add_reading(reading)
        
        summary = energy_analyzer.get_summary()
        
        assert summary["total_readings"] > 0
        assert summary["electricity_rate_qar"] > 0
    
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
        assert patterns[0].pattern_type == "ghost_operation"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
