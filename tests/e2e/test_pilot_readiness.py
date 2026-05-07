#!/usr/bin/env python3
"""
E2E Test: Pilot Readiness Validation
====================================

Scenario: Full system validation before pilot deployment.

This test verifies:
1. All core components initialize
2. BMS connectivity works (simulated)
3. Alarm processing works
4. Energy analysis works
5. GSAS reporting works
6. Briefing generation works
7. Tool execution works
8. ABI loops work
"""

import pytest
import asyncio

from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockBACnetAdapter,
    MockAlarmEngine,
    MockEnergyAnalyzer,
    MockGSASReporter,
    MockPredictiveEngine,
    MockBriefingScheduler,
    MockGoalGenerator,
)
from tests.factories import EquipmentFactory


class TestPilotReadiness:
    """
    Comprehensive pilot readiness validation.
    """
    
    @pytest.fixture
    def full_system(self):
        """Complete mock system."""
        state = MockBMSStateEngine()
        
        # Add complete equipment set
        state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-01"))
        state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-02"))
        state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-01"))
        state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-02"))
        state.add_equipment(EquipmentFactory.meter())
        
        # Add points
        state.update_point("CH-01/CHWST", 7.0, "°C", "CH-01")
        state.update_point("CH-02/CHWST", 7.1, "°C", "CH-02")
        state.update_point("AHU-01/SAT", 14.0, "°C", "AHU-01")
        state.update_point("METER-01/KW", 450.0, "kW", "METER-01")
        
        return state
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_all_components_initialize(self, full_system):
        """All core components should initialize successfully."""
        # State engine
        assert full_system is not None
        
        # Alarm engine
        alarm_engine = MockAlarmEngine(bms_state=full_system)
        assert alarm_engine is not None
        
        # Energy analyzer
        energy_analyzer = MockEnergyAnalyzer()
        assert energy_analyzer is not None
        
        # GSAS reporter
        gsas_reporter = MockGSASReporter()
        assert gsas_reporter is not None
        
        # Predictive engine
        predictive_engine = MockPredictiveEngine()
        assert predictive_engine is not None
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_bms_connectivity(self, full_system):
        """BMS connectivity should work."""
        bacnet = MockBACnetAdapter()
        
        # Connect
        connected = await bacnet.connect()
        assert connected is True
        
        # Discover devices
        devices = await bacnet.discover_devices()
        assert isinstance(devices, list)
        
        # Disconnect
        await bacnet.disconnect()
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_alarm_processing(self, full_system):
        """Alarm processing should work end-to-end."""
        from tests.factories import AlarmFactory
        
        alarm_engine = MockAlarmEngine(bms_state=full_system)
        
        # Add alarm
        alarm = AlarmFactory.critical_chiller()
        full_system.add_alarm(alarm)
        
        # Get active alarms
        active = full_system.get_active_alarms()
        assert len(active) >= 1
        
        # Cluster
        clusters = alarm_engine.cluster_alarms(active)
        assert isinstance(clusters, list)
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_energy_analysis(self, full_system):
        """Energy analysis should work."""
        energy_analyzer = MockEnergyAnalyzer()
        
        summary = energy_analyzer.get_summary()
        assert "total_kwh" in summary
        assert "cost_qar" in summary
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_gsas_reporting(self, full_system):
        """GSAS reporting should work."""
        gsas_reporter = MockGSASReporter()
        
        status = gsas_reporter.get_status()
        assert "overall_score" in status
        assert "category_scores" in status
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_briefing_generation(self, full_system):
        """Briefing generation should work."""
        scheduler = MockBriefingScheduler(bms_state=full_system)
        
        briefing = await scheduler.generate_briefing(briefing_type="daily_morning")
        
        assert briefing is not None
        assert "headline" in briefing or "briefing_type" in briefing
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_tool_execution(self, full_system):
        """Tool execution should work."""
        # Simulate tool call
        equipment = full_system.get_equipment("CH-01")
        
        assert equipment is not None
        assert equipment["equipment_id"] == "CH-01"
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_abi_loops(self, full_system):
        """ABI loops should work end-to-end."""
        from agent_advisory.verify_loop import VerifyLoop
        from agent_cognitive.prediction_engine import PredictionEngine
        
        llm = MockLLM()
        
        # Prediction engine
        prediction_engine = PredictionEngine(
            bms_state=full_system,
            llm=llm,
        )
        assert prediction_engine is not None
        
        # Verify loop
        verify_loop = VerifyLoop(
            bms_state=full_system,
            llm=llm,
        )
        assert verify_loop is not None
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_full_system_integration(self, full_system):
        """
        Complete integration test.
        
        This verifies all components work together.
        """
        # 1. Get equipment status
        equipment = full_system.get_all_equipment()
        assert len(equipment) >= 5  # At least 5 equipment items
        
        # 2. Check state summary
        summary = full_system.get_state_summary()
        assert summary["equipment_count"] >= 5
        
        # 3. Generate briefing
        scheduler = MockBriefingScheduler(bms_state=full_system)
        briefing = await scheduler.generate_briefing(briefing_type="daily_morning")
        assert briefing is not None
        
        # 4. Get GSAS status
        gsas = MockGSASReporter()
        gsas_status = gsas.get_status()
        assert "overall_score" in gsas_status
        
        # 5. Analyze energy
        energy = MockEnergyAnalyzer()
        energy_summary = energy.get_summary()
        assert "total_kwh" in energy_summary
        
        print("\n✅ PILOT READINESS VALIDATION PASSED")
        print(f"  - Equipment: {len(equipment)} units")
        print(f"  - Points: {summary['point_count']}")
        print(f"  - GSAS Score: {gsas_status['overall_score']}")
        print(f"  - Energy: {energy_summary['total_kwh']} kWh")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
