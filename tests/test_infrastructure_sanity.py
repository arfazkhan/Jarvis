#!/usr/bin/env python3
"""
Sanity Test: Verify Test Infrastructure
=======================================

Quick test to ensure all Phase 1 infrastructure works correctly.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMockInfrastructure:
    """Test that all mocks work correctly."""
    
    def test_mock_llm_basic(self):
        """MockLLM returns configured responses."""
        from tests.mocks import MockLLM
        
        llm = MockLLM(responses={"status": '{"running": true}'})
        result = await llm.ask("What is the status?")
        
        assert result == '{"running": true}'
    
    def test_mock_llm_timeout(self):
        """MockLLM can simulate timeout."""
        from tests.mocks import MockLLM
        
        llm = MockLLM()
        llm.timeout_after(0.01)
        
        with pytest.raises(asyncio.TimeoutError):
            await llm.ask("test")
    
    def test_mock_llm_rate_limit(self):
        """MockLLM can simulate rate limit."""
        from tests.mocks import MockLLM
        
        llm = MockLLM()
        llm.rate_limit()
        
        with pytest.raises(Exception, match="Rate limit"):
            await llm.ask("test")
    
    def test_mock_bacnet_equipment(self):
        """MockBACnetAdapter manages equipment correctly."""
        from tests.mocks import MockBACnetAdapter
        
        adapter = MockBACnetAdapter()
        adapter.add_device(1001, "Chiller-01", "192.168.1.101")
        adapter.add_point("CH-01/KW", 250.0, "kW", device_id=1001)
        
        point = await adapter.read_point("CH-01/KW")
        
        assert point["point_id"] == "CH-01/KW"
        assert point["unit"] == "kW"
        assert point["device_id"] == 1001
    
    def test_mock_bms_state_equipment(self):
        """MockBMSStateEngine manages equipment correctly."""
        from tests.mocks import MockBMSStateEngine
        
        state = MockBMSStateEngine()
        state.add_equipment({"equipment_id": "CH-01", "name": "Chiller 1"})
        state.update_point("CH-01/CHWST", 7.0, equipment_id="CH-01")
        
        equipment = state.get_equipment("CH-01")
        point = state.get_point("CH-01/CHWST")
        
        assert equipment["equipment_id"] == "CH-01"
        assert point["value"] == 7.0


class TestFactories:
    """Test that all factories work correctly."""
    
    def test_equipment_factory_chiller(self):
        """EquipmentFactory creates chiller dicts."""
        from tests.factories import EquipmentFactory
        
        chiller = EquipmentFactory.chiller()
        
        assert chiller["equipment_id"] == "CH-01"
        assert chiller["equipment_type"] == "chiller"
        assert "status" in chiller
    
    def test_equipment_factory_custom(self):
        """EquipmentFactory supports customization."""
        from tests.factories import EquipmentFactory
        
        chiller = EquipmentFactory.chiller(
            equipment_id="CH-99",
            status="fault",
            efficiency=0.50
        )
        
        assert chiller["equipment_id"] == "CH-99"
        assert chiller["status"] == "fault"
        assert chiller["efficiency"] == 0.50
    
    def test_alarm_factory_critical(self):
        """AlarmFactory creates critical alarm dicts."""
        from tests.factories import AlarmFactory
        
        alarm = AlarmFactory.critical_chiller()
        
        assert alarm["severity"] == "critical"
        assert alarm["status"] == "active"
    
    def test_alarm_factory_flood(self):
        """AlarmFactory can generate alarm floods."""
        from tests.factories import AlarmFactory
        
        alarms = AlarmFactory.flood(count=100)
        
        assert len(alarms) == 100
        assert all("alarm_id" in a for a in alarms)
    
    def test_energy_reading_factory_24h(self):
        """EnergyReadingFactory generates 24h of readings."""
        from tests.factories import EnergyReadingFactory
        
        readings = EnergyReadingFactory.last_24_hours()
        
        assert len(readings) == 24
        assert all("total_kw" in r for r in readings)


class TestUtilities:
    """Test that all utilities work correctly."""
    
    def test_assert_valid_tool_result_success(self):
        """assert_valid_tool_result accepts valid success results."""
        from tests.utils import assert_valid_tool_result
        
        result = {"status": "success", "data": {"test": "value"}}
        
        # Should not raise
        assert_valid_tool_result(result)
    
    def test_assert_valid_tool_result_error(self):
        """assert_valid_tool_result accepts valid error results."""
        from tests.utils import assert_valid_tool_result
        
        result = {"status": "error", "error": "Something failed"}
        
        # Should not raise
        assert_valid_tool_result(result)
    
    def test_assert_valid_tool_result_invalid(self):
        """assert_valid_tool_result rejects invalid results."""
        from tests.utils import assert_valid_tool_result
        
        result = {"status": "invalid"}
        
        with pytest.raises(AssertionError):
            assert_valid_tool_result(result)
    
    def test_assert_valid_recommendation(self):
        """assert_valid_recommendation validates recommendations."""
        from tests.utils import assert_valid_recommendation
        
        rec = {
            "recommendation_id": "REC-001",
            "equipment_id": "CH-01",
            "action": "test_action",
            "confidence": 0.85,
            "gsas_aligned": True,
        }
        
        # Should not raise
        assert_valid_recommendation(rec)
    
    def test_assert_valid_gsas_score(self):
        """assert_valid_gsas_score validates GSAS scores."""
        from tests.utils import assert_valid_gsas_score
        
        score = {
            "overall_score": 2.5,
            "star_rating": 4,
            "categories": {"E": 1.5, "W": 1.0},
        }
        
        # Should not raise
        assert_valid_gsas_score(score)
    
    def test_timer(self):
        """Timer context manager works correctly."""
        from tests.utils import Timer
        import time
        
        with Timer("test_operation") as t:
            time.sleep(0.1)
        
        assert t.duration_ms >= 100
        assert "test_operation" in str(t)


class TestScenarioBuilder:
    """Test ScenarioBuilder functionality."""
    
    def test_scenario_builder_basic(self):
        """ScenarioBuilder creates basic scenarios."""
        from tests.utils.helpers import ScenarioBuilder
        
        scenario = (ScenarioBuilder()
            .add_chiller("CH-01")
            .add_ahu("AHU-01")
            .build())
        
        assert len(scenario["equipment"]) == 2
        assert len(scenario["points"]) >= 4
    
    def test_scenario_builder_with_alarms(self):
        """ScenarioBuilder can add alarms."""
        from tests.utils.helpers import ScenarioBuilder
        
        scenario = (ScenarioBuilder()
            .add_chiller("CH-01")
            .add_critical_alarm("CH-01")
            .build())
        
        assert len(scenario["alarms"]) == 1
        assert scenario["alarms"][0]["severity"] == "critical"


class TestFixtureIntegration:
    """Test that pytest fixtures would work (manual verification)."""
    
    def test_mock_llm_fixture_would_work(self):
        """Verify mock_llm fixture structure."""
        from tests.mocks import MockLLM
        
        # This is what the fixture would do
        llm = MockLLM(latency_ms=10.0)
        
        assert llm.latency_ms == 10.0
        assert llm.responses == {}
    
    def test_mock_bms_state_fixture_would_work(self):
        """Verify mock_bms_state fixture structure."""
        from tests.mocks import create_mock_bms_state_with_equipment
        
        # This is what the fixture would do
        state = create_mock_bms_state_with_equipment()
        
        assert len(state.get_all_equipment()) == 2
        assert state.get_equipment("CH-01") is not None
        assert state.get_equipment("AHU-01") is not None


# ============================================================================
# RUN TESTS
# ============================================================================

import asyncio

# Run all tests
if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v"])
    sys.exit(exit_code)
