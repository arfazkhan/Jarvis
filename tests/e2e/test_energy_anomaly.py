#!/usr/bin/env python3
"""
E2E Test: Energy Anomaly Detection
===================================

Scenario: Energy waste detected → operator investigates → issue fixed.

Full workflow:
1. System detects ghost operation (cooling empty room)
2. Operator receives morning briefing with anomaly
3. Operator investigates specific zone
4. System estimates occupancy using virtual sensors
5. Operator adjusts schedule
6. System validates savings
"""

import pytest
import asyncio

from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockEnergyAnalyzer,
)
from tests.factories import EquipmentFactory, EnergyReadingFactory


class TestEnergyAnomaly:
    """
    Test energy anomaly detection and resolution workflow.
    """
    
    @pytest.fixture
    def building_with_ghost(self):
        """Create building with ghost operation."""
        state = MockBMSStateEngine()
        
        # Equipment
        state.add_equipment(EquipmentFactory.chiller())
        state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-01"))
        
        # Zone with ghost operation
        state.add_zone({
            "zone_id": "ZONE-F1-01",
            "name": "Conference Room A",
            "floor": "Floor 1",
            "co2_ppm": 415,  # Empty (low CO2)
            "vav_damper_pct": 75,  # But VAV is open
            "light_status": False,  # Lights off
            "load_kw": 3.2,  # Cooling active
            "scheduled_status": "OCCUPIED",  # Schedule says occupied
        })
        
        return state
    
    @pytest.fixture
    def energy_analyzer(self):
        """Energy analyzer with detected waste."""
        analyzer = MockEnergyAnalyzer(
            total_kwh=520.0,
            cost_qar=78.0,
        )
        
        # Add detected ghost operation
        analyzer.add_waste_pattern({
            "pattern_id": "WASTE-001",
            "pattern_type": "ghost_operation",
            "description": "Zone F1-01 cooling while empty",
            "occurrences": 15,
            "estimated_waste_qar_day": 45.0,
            "zone_id": "ZONE-F1-01",
        })
        
        return analyzer
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_ghost_operation_detected(self, building_with_ghost, energy_analyzer):
        """System should detect ghost operation automatically."""
        # Get energy summary
        summary = energy_analyzer.get_summary()
        
        assert summary["total_kwh"] > 500
        
        # Get waste patterns
        patterns = energy_analyzer.identify_waste_patterns()
        
        assert len(patterns) >= 1
        ghost_pattern = next(
            (p for p in patterns if p["pattern_type"] == "ghost_operation"),
            None
        )
        
        assert ghost_pattern is not None
        assert ghost_pattern["estimated_waste_qar_day"] > 0
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_virtual_sensor_estimates_occupancy(self, building_with_ghost):
        """Virtual sensor should correctly estimate zone is empty."""
        zone = await building_with_ghost.get_zone_with_current_values("ZONE-F1-01")
        
        assert zone is not None
        
        # Low CO2 indicates empty
        assert zone["co2_ppm"] < 500
        
        # But cooling is active
        assert zone["vav_damper_pct"] > 50
        
        # Virtual sensor should identify this as ghost operation
        from agent_commercial.virtual_sensors import VirtualOccupancySensor
        
        sensor = VirtualOccupancySensor()
        estimate = sensor.estimate_occupancy(
            zone_id=zone["zone_id"],
            co2_ppm=zone["co2_ppm"],
            vav_damper_pct=zone["vav_damper_pct"],
            light_status=zone["light_status"],
        )
        
        assert estimate.probability < 0.3  # Should detect low occupancy
        assert estimate.level in ["empty", "low"]
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_operator_investigates_and_fixes(self, building_with_ghost, energy_analyzer):
        """Complete workflow from detection to fix."""
        # 1. Operator sees waste pattern in briefing
        patterns = energy_analyzer.identify_waste_patterns()
        ghost_pattern = patterns[0]
        
        # 2. Operator investigates zone
        zone = await building_with_ghost.get_zone_with_current_values("ZONE-F1-01")
        
        # 3. Operator confirms it's empty via virtual sensor
        from agent_commercial.virtual_sensors import VirtualOccupancySensor
        sensor = VirtualOccupancySensor()
        estimate = sensor.estimate_occupancy(
            zone_id=zone["zone_id"],
            co2_ppm=zone["co2_ppm"],
            vav_damper_pct=zone["vav_damper_pct"],
            light_status=zone["light_status"],
        )
        
        # 4. Operator adjusts schedule (simulated)
        # Would call: update_zone_schedule(zone_id="ZONE-F1-01", status="UNOCCUPIED")
        
        # 5. Verify potential savings
        daily_savings = ghost_pattern["estimated_waste_qar_day"]
        monthly_savings = daily_savings * 30
        
        assert monthly_savings > 1000  # Should be significant savings


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
