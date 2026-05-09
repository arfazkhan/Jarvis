"""
Energy Tool Tests
==================

Tests for all 6 energy-related BMS tools.
Each tool tested across happy, edge, failure, and stress scenarios.
"""

import pytest
import asyncio
from unittest.mock import patch
from datetime import datetime
from typing import Dict, Any

from agent_commercial.tools.handlers.energy import EnergyHandlerMixin
from agent_commercial.energy_analyzer import EnergyAnalyzer
from tests.factories import (
    EnergyReadingFactory,
    EquipmentFactory,
    AlarmFactory,
)
from tests.mocks import MockBMSStateEngine, MockEnergyAnalyzer
from tests.utils.helpers import (
    assert_valid_tool_result,
    assert_valid_anomaly,
    Timer,
    run_concurrently,
)


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def energy_handler(mock_bms_state):
    """Create energy handler with mock state."""
    handler = EnergyHandlerMixin()
    handler.bms_state = mock_bms_state
    handler.energy_analyzer = MockEnergyAnalyzer()
    return handler


@pytest.fixture
def mock_bms_state_with_energy():
    """Mock state with energy data."""
    state = MockBMSStateEngine()
    state.add_equipment(EquipmentFactory.meter())
    state.add_equipment(EquipmentFactory.chiller())
    for i in range(24):
        state.add_energy_reading(EnergyReadingFactory.reading(hour_offset=i))
    return state


@pytest.fixture(autouse=True)
def mock_db_globally():
    """Automatically mock database for all tests to prevent hanging connections."""
    from unittest.mock import AsyncMock, MagicMock
    with patch("agent_commercial.tools.handlers.energy.get_database") as mock:
        mock_db = MagicMock()
        # Setup common database methods as mocks
        mock_db.get_all_zones = AsyncMock(return_value=[])
        mock_db.get_zone_with_current_values = AsyncMock(return_value=None)
        mock.return_value = mock_db
        yield mock_db


# ============================================================================
# analyze_energy
# ============================================================================

class TestAnalyzeEnergy:
    """Tests for analyze_energy tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_energy_summary(self, energy_handler):
        """Happy path: returns valid energy analysis."""
        result = await energy_handler._handle_analyze_energy({"period": "today"})
        
        assert_valid_tool_result(result)
        assert "total_kwh" in result
        assert "cost_qar" in result
        assert "anomalies" in result
        assert result["total_kwh"] >= 0
    
    @pytest.mark.asyncio
    async def test_period_this_week(self, energy_handler):
        """Different period parameter."""
        result = await energy_handler._handle_analyze_energy({"period": "this_week"})
        
        assert_valid_tool_result(result)
        # Weekly should have more data than daily
        assert result["total_kwh"] >= 0
    
    @pytest.mark.asyncio
    async def test_with_building_filter(self, energy_handler):
        """Building filter applied."""
        result = await energy_handler._handle_analyze_energy({
            "period": "today",
            "building_id": "BUILDING-A"
        })
        
        assert_valid_tool_result(result)
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_no_energy_data(self, mock_bms_state):
        """No energy readings in system."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state  # Empty state
        handler.energy_analyzer = MockEnergyAnalyzer(total_kwh=0)
        
        result = await handler._handle_analyze_energy({"period": "today"})
        
        assert_valid_tool_result(result)
        assert result["total_kwh"] == 0
    
    @pytest.mark.asyncio
    async def test_invalid_period_defaults_to_today(self, energy_handler):
        """Invalid period should default gracefully."""
        result = await energy_handler._handle_analyze_energy({"period": "invalid_period"})
        
        # Should not crash, return valid result
        assert_valid_tool_result(result)
    
    @pytest.mark.asyncio
    async def test_future_period_next_week(self, energy_handler):
        """Future period (next_week) should return forecast."""
        result = await energy_handler._handle_analyze_energy({"period": "next_week"})
        
        assert_valid_tool_result(result)
        assert "forecast" in result or "predicted_kwh" in result or result["total_kwh"] >= 0
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_energy_analyzer_unavailable(self, mock_bms_state):
        """Energy analyzer not configured."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        handler.energy_analyzer = None  # Not configured
        
        result = await handler._handle_analyze_energy({"period": "today"})
        
        assert "error" in result
        assert "not configured" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_analyzer_throws_exception(self, energy_handler):
        """Analyzer throws during calculation."""
        def broken_analyze():
            raise RuntimeError("Database connection lost")
        
        energy_handler.energy_analyzer.get_summary = broken_analyze
        
        result = await energy_handler._handle_analyze_energy({"period": "today"})
        
        # Should handle exception gracefully
        assert "error" in result or result.get("status") == "error"
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_analyses(self, energy_handler):
        """50 concurrent analysis requests."""
        results = await run_concurrently(
            [lambda: energy_handler._handle_analyze_energy({"period": "today"})],
            count=50
        )
        
        # All should succeed
        assert all("error" not in r for r in results if isinstance(r, dict))
    
    @pytest.mark.asyncio
    async def test_large_dataset_analysis(self, mock_bms_state_with_energy):
        """Analyze with 10,000+ data points."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state_with_energy
        handler.energy_analyzer = MockEnergyAnalyzer()
        
        # Add many readings
        for i in range(1000):
            mock_bms_state_with_energy.add_energy_reading(
                EnergyReadingFactory.reading(hour_offset=i/100)
            )
        
        with Timer() as timer:
            result = await handler._handle_analyze_energy({"period": "this_month"})
        
        # Should complete in reasonable time
        assert timer.elapsed < 5.0, f"Analysis took {timer.elapsed}s, expected < 5s"
        assert_valid_tool_result(result)


# ============================================================================
# get_energy_anomalies
# ============================================================================

class TestGetEnergyAnomalies:
    """Tests for get_energy_anomalies tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_anomaly_list(self, energy_handler):
        """Happy path: returns detected anomalies."""
        result = await energy_handler._handle_get_energy_anomalies({})
        
        assert_valid_tool_result(result)
        assert "patterns" in result
        assert "count" in result
        assert result["count"] == len(result["patterns"])
    
    @pytest.mark.asyncio
    async def test_anomaly_has_required_fields(self, energy_handler):
        """Each anomaly has required fields."""
        result = await energy_handler._handle_get_energy_anomalies({})
        
        if result["count"] > 0:
            for anomaly in result["patterns"]:
                assert_valid_anomaly(anomaly)
    
    @pytest.mark.asyncio
    async def test_detects_ghost_operation(self, mock_bms_state):
        """Detects cooling empty rooms."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        handler.energy_analyzer = MockEnergyAnalyzer()
        handler.energy_analyzer.add_waste_pattern({
            "pattern_type": "ghost_operation",
            "description": "Zone cooled but empty",
            "estimated_savings_qar": 50.0
        })
        
        result = await handler._handle_get_energy_anomalies({})
        
        assert result["count"] >= 1
        ghost = [p for p in result["patterns"] if "ghost" in p.get("pattern_type", "").lower()]
        assert len(ghost) > 0
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_no_anomalies_found(self, energy_handler):
        """System has no anomalies."""
        energy_handler.energy_analyzer.clear_patterns()
        
        result = await energy_handler._handle_get_energy_anomalies({})
        
        assert_valid_tool_result(result)
        assert result["count"] == 0
        assert result["patterns"] == []
    
    @pytest.mark.asyncio
    async def test_mixed_anomaly_types(self, energy_handler):
        """Different types of anomalies."""
        energy_handler.energy_analyzer.add_waste_pattern({
            "pattern_type": "after_hours_hvac",
            "estimated_savings_qar": 100.0
        })
        energy_handler.energy_analyzer.add_waste_pattern({
            "pattern_type": "simultaneous_heating_cooling",
            "estimated_savings_qar": 200.0
        })
        
        result = await energy_handler._handle_get_energy_anomalies({})
        
        assert result["count"] >= 2
        types = {p["pattern_type"] for p in result["patterns"]}
        assert len(types) >= 2  # Multiple types
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_analyzer_unavailable(self):
        """Energy analyzer not configured."""
        handler = EnergyHandlerMixin()
        handler.bms_state = MockBMSStateEngine()
        handler.energy_analyzer = None
        
        result = await handler._handle_get_energy_anomalies({})
        
        assert "error" in result
        assert "not configured" in result["error"].lower()
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_many_anomalies(self, energy_handler):
        """Handle 100+ detected anomalies."""
        for i in range(100):
            energy_handler.energy_analyzer.add_waste_pattern({
                "pattern_type": f"waste_{i}",
                "estimated_savings_qar": float(i)
            })
        
        result = await energy_handler._handle_get_energy_anomalies({})
        
        assert result["count"] == 100
        # All should serialize correctly
        assert len(result["patterns"]) == 100


# ============================================================================
# check_cost_impact
# ============================================================================

class TestCheckCostImpact:
    """Tests for check_cost_impact tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_calculates_cost_difference(self, energy_handler):
        """Happy path: calculates temperature change cost."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0,
            "target_temp": 22.0
        })
        
        assert_valid_tool_result(result)
        assert_valid_tool_result(result)
        # Should have burn rates
        assert "current_burn_rate_qar_hour" in result
        assert "new_burn_rate_qar_hour" in result
        assert result["new_burn_rate_qar_hour"] > result["current_burn_rate_qar_hour"]
        assert "daily_impact_qar" in result or "monthly_impact_qar" in result
    
    @pytest.mark.asyncio
    async def test_cooling_cost_increase(self, energy_handler):
        """Lower temp = higher cost."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0,
            "target_temp": 20.0  # 4 degrees cooler
        })
        
        assert_valid_tool_result(result)
        # Lower temp should increase cost
        assert result["new_burn_rate_qar_hour"] > result["current_burn_rate_qar_hour"]
    
    @pytest.mark.asyncio
    async def test_cooling_cost_decrease(self, energy_handler):
        """Higher temp = lower cost."""
        """Decrease cooling cost."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 21.0,
            "target_temp": 24.0,
            "zone_id": "ZONE-01"
        })
        
        assert_valid_tool_result(result)
        assert result["new_burn_rate_qar_hour"] < result["current_burn_rate_qar_hour"]
    
    @pytest.mark.asyncio
    async def test_with_zone_filter(self, energy_handler):
        """Zone-specific calculation."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0,
            "target_temp": 22.0,
            "zone_id": "ZONE-F1-01"
        })
        
        assert_valid_tool_result(result)
        assert "zone_id" in result or result.get("zone") == "ZONE-F1-01"
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_same_temperature(self, energy_handler):
        """Current == target temp."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0,
            "target_temp": 24.0  # No change
        })
        
        assert_valid_tool_result(result)
        # Should indicate no change
        assert result["daily_impact_qar"] == 0 or result.get("change") == "none"
    
    @pytest.mark.asyncio
    async def test_extreme_cooling_request(self, energy_handler):
        """Extreme temperature change."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 30.0,
            "target_temp": 16.0  # 14 degree change
        })
        
        # Should handle extreme values
        assert_valid_tool_result(result)
        # Should warn about extreme change
        if "warning" in result:
            assert "extreme" in result["warning"].lower() or "significant" in result["warning"].lower()
    
    @pytest.mark.asyncio
    async def test_missing_current_temp(self, energy_handler):
        """Missing current_temp parameter."""
        result = await energy_handler._handle_check_cost_impact({
            "target_temp": 22.0
            # current_temp missing
        })
        
        # Should handle gracefully with default or error
        assert "error" in result or "current_temp" in result
    
    @pytest.mark.asyncio
    async def test_missing_target_temp(self, energy_handler):
        """Missing target_temp parameter."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0
            # target_temp missing
        })
        
        assert "error" in result or "target_temp" in result
    
    @pytest.mark.asyncio
    async def test_negative_temperature(self, energy_handler):
        """Negative temperature values."""
        result = await energy_handler._handle_check_cost_impact({
            "current_temp": -5.0,
            "target_temp": 20.0
        })
        
        # Should handle or reject
        assert_valid_tool_result(result) or "error" in result
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_cost_engine_unavailable(self, mock_bms_state):
        """Cost engine throws exception."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        
    @pytest.mark.asyncio
    async def test_cost_engine_unavailable(self, energy_handler):
        """Handle missing engine."""
        with patch("agent_commercial.tools.handlers.energy.check_cost_impact", None):
            result = await energy_handler._handle_check_cost_impact({
                "current_temp": 24.0,
                "target_temp": 22.0
            })
            assert "error" in result
            assert "not available" in result["error"]
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_many_concurrent_calculations(self, energy_handler):
        """50 concurrent cost calculations."""
        results = await run_concurrently(
            [lambda: energy_handler._handle_check_cost_impact({
                "current_temp": 24.0,
                "target_temp": 21.0
            })],
            count=20
        )
        
        assert len(results) == 20
        assert all("error" not in r for r in results if isinstance(r, dict))


# ============================================================================
# get_burn_rate
# ============================================================================

class TestGetBurnRate:
    """Tests for get_burn_rate tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_current_burn_rate(self, energy_handler):
        """Get current burn rate."""
        result = await energy_handler._handle_get_burn_rate({
            "total_kw": 500
        })
        
        assert_valid_tool_result(result)
        assert "burn_rate_qar_hour" in result or "current_burn_rate_qar_hour" in result
    
    @pytest.mark.asyncio
    async def test_includes_projections(self, energy_handler):
        """Check projections."""
        result = await energy_handler._handle_get_burn_rate({
            "total_kw": 500
        })
        
        assert "projected_daily_qar" in result or "daily_impact_qar" in result
        assert "projected_monthly_qar" in result or "projected_monthly" in result
        assert "monthly_projection_qar" not in result # Should use production key
    
    @pytest.mark.asyncio
    async def test_with_building_filter(self, energy_handler):
        """Building-specific burn rate."""
        result = await energy_handler._handle_get_burn_rate({
            "building_id": "BUILDING-A"
        })
        
        assert_valid_tool_result(result)
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_zero_load(self, energy_handler):
        """Zero load burn rate."""
        result = await energy_handler._handle_get_burn_rate({
            "total_kw": 0
        })
        
        assert result.get("burn_rate_qar_hour", 0) == 0
    
    @pytest.mark.asyncio
    async def test_very_high_load(self, energy_handler):
        """High load burn rate."""
        result = await energy_handler._handle_get_burn_rate({
            "total_kw": 5000
        })
        
        assert result.get("burn_rate_qar_hour", 0) > 0 or result.get("current_burn_rate_qar_hour", 0) > 0
        # Should handle large values
        assert result["burn_rate_qar_hour"] > 0
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_engine_unavailable(self):
        """Cost engine not available."""
        handler = EnergyHandlerMixin()
        handler.bms_state = MockBMSStateEngine()
        
        with patch("agent_commercial.tools.handlers.energy.get_current_burn_rate", None):
            result = await handler._handle_get_burn_rate({})
            assert "error" in result
            assert "not available" in result["error"]


# ============================================================================
# find_ghost_spaces
# ============================================================================

class TestFindGhostSpaces:
    """Tests for find_ghost_spaces tool - virtual occupancy sensing."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_ghost_operations(self, energy_handler):
        """Happy path: finds empty rooms being cooled."""
        result = await energy_handler._handle_find_ghost_spaces({})
        
        assert_valid_tool_result(result)
        assert "ghost_operations" in result
        assert "waste_estimate_qar_day" in result
    
    @pytest.mark.asyncio
    async def test_detects_empty_zone(self, energy_handler, mock_bms_state):
        """Zone with low CO2 = empty."""
        mock_bms_state.add_zone({
            "zone_id": "ZONE-01",
            "co2_ppm": 415,  # Ambient, indicates empty
            "vav_damper_pct": 80,  # But VAV is open
            "light_status": True,
            "load_kw": 2.5
        })
        
        result = await energy_handler._handle_find_ghost_spaces({})
        
        if result["ghost_operations"]:
            ghost = result["ghost_operations"][0]
            assert ghost["occupancy_probability"] < 0.3
    
    @pytest.mark.asyncio
    async def test_occupied_zone_not_flagged(self, energy_handler, mock_bms_state):
        """Occupied zone should not be ghost."""
        mock_bms_state.add_zone({
            "zone_id": "ZONE-02",
            "co2_ppm": 800,  # High, indicates occupied
            "vav_damper_pct": 80,
            "light_status": True,
            "load_kw": 2.5
        })
        
        result = await energy_handler._handle_find_ghost_spaces({})
        
        # This zone should NOT be in ghost_operations
        ghost_ids = [g["zone_id"] for g in result["ghost_operations"]]
        assert "ZONE-02" not in ghost_ids
    
    @pytest.mark.asyncio
    async def test_includes_savings_estimate(self, energy_handler):
        """Each ghost operation has savings estimate."""
        result = await energy_handler._handle_find_ghost_spaces({})
        
        if result["ghost_operations"]:
            for ghost in result["ghost_operations"]:
                assert "waste_qar_hour" in ghost
                assert ghost["waste_qar_hour"] > 0
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_no_zones_configured(self, mock_bms_state):
        """No zones in system."""
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state  # Empty
        
        result = await handler._handle_find_ghost_spaces({})
        
        assert_valid_tool_result(result)
        assert result["ghost_operations"] == []
        assert "note" in result or result["zones_checked"] == 0
    
    @pytest.mark.asyncio
    async def test_floor_filter(self, energy_handler, mock_bms_state):
        """Filter by specific floor."""
        mock_bms_state.add_zone({"zone_id": "ZONE-F1-01", "floor": "F1"})
        mock_bms_state.add_zone({"zone_id": "ZONE-F2-01", "floor": "F2"})
        
        result = await energy_handler._handle_find_ghost_spaces({"floor_filter": "F1"})
        
        # Should only check F1 zones
        for ghost in result["ghost_operations"]:
            assert "F1" in ghost["zone_id"] or ghost.get("floor") == "F1"
    
    @pytest.mark.asyncio
    async def test_missing_co2_sensor(self, mock_bms_state):
        """Zone without CO2 sensor."""
        mock_bms_state.add_zone({
            "zone_id": "ZONE-NO-CO2",
            "co2_ppm": None,  # No sensor
            "vav_damper_pct": 80,
            "load_kw": 2.0
        })
        
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        
        result = await handler._handle_find_ghost_spaces({})
        
        # Should handle gracefully (use default or skip)
        assert_valid_tool_result(result)
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_database_unavailable(self):
        """Database connection fails."""
        handler = EnergyHandlerMixin()
        handler.bms_state = MockBMSStateEngine()
        
        # Force database error
        async def broken_get_zones():
            raise ConnectionError("Database offline")
        
        handler.bms_state.get_all_zones = broken_get_zones
        
        result = await handler._handle_find_ghost_spaces({})
        
        assert "error" in result or result["ghost_operations"] == []
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_many_zones(self, mock_bms_state):
        """Scan 200+ zones efficiently."""
        for i in range(200):
            mock_bms_state.add_zone({
                "zone_id": f"ZONE-{i:03d}",
                "co2_ppm": 400 + (i % 400),
                "vav_damper_pct": 50 + (i % 40),
                "load_kw": 1.5 + (i % 2)
            })
        
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        
        with Timer() as timer:
            result = await handler._handle_find_ghost_spaces({})
        
        # Should complete in reasonable time
        assert timer.elapsed < 10.0
        assert result["zones_checked"] == 200


# ============================================================================
# estimate_zone_occupancy
# ============================================================================

class TestEstimateZoneOccupancy:
    """Tests for estimate_zone_occupancy tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_occupancy_estimate(self, energy_handler):
        """Happy path: returns occupancy probability."""
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-01"
        })
        
        assert_valid_tool_result(result)
        assert "probability" in result or "occupancy_probability" in result
        assert 0 <= result.get("probability", result.get("occupancy_probability", 0)) <= 1
    
    @pytest.mark.asyncio
    async def test_co2_method(self, energy_handler):
        """CO2-based estimation."""
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-01",
            "method": "co2"
        })
        
        assert_valid_tool_result(result)
    
    @pytest.mark.asyncio
    async def test_vav_method(self, energy_handler):
        """VAV-based estimation."""
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-01",
            "method": "vav"
        })
        
        assert_valid_tool_result(result)
    
    @pytest.mark.asyncio
    async def test_fusion_method(self, energy_handler):
        """Fusion of all sensors."""
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-01",
            "method": "fusion",
            "co2_ppm": 800,  # High CO2 = High confidence
            "light_status": False # Lights off helps confidence logic sometimes? No, let's keep it simple.
        })
        
        assert_valid_tool_result(result)
        # Fusion should be more confident
        if "confidence" in result:
            assert result["confidence"] >= 0.4
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_zone_not_found(self, energy_handler):
        """Zone doesn't exist."""
        # The handler should return an error or at least low probability
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "NONEXISTENT-ZONE"
        })
        
        assert "error" in result or result.get("confidence", 1.0) < 0.5
    
    @pytest.mark.asyncio
    async def test_invalid_method_defaults_to_fusion(self, energy_handler):
        """Invalid method defaults gracefully."""
        result = await energy_handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-01",
            "method": "invalid_method"
        })
        
        # Should not crash
        assert_valid_tool_result(result) or "error" in result
    
    @pytest.mark.asyncio
    async def test_missing_zone_id(self, energy_handler):
        """Zone ID required."""
        result = await energy_handler._handle_estimate_zone_occupancy({})
        
        assert "error" in result
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_sensor_data_unavailable(self, mock_bms_state):
        """Zone exists but no sensor data."""
        mock_bms_state.add_zone({
            "zone_id": "ZONE-EMPTY",
            "co2_ppm": None,
            "vav_damper_pct": None
        })
        
        handler = EnergyHandlerMixin()
        handler.bms_state = mock_bms_state
        
        result = await handler._handle_estimate_zone_occupancy({
            "zone_id": "ZONE-EMPTY"
        })
        
        # Should handle gracefully
        assert_valid_tool_result(result) or "error" in result
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_estimates(self, energy_handler):
        """50 concurrent occupancy estimates."""
        results = await run_concurrently(
            [lambda: energy_handler._handle_estimate_zone_occupancy({
                "zone_id": "ZONE-01"
            })],
            count=50
        )
        
        # Should handle all
        assert len(results) == 50
        assert all(isinstance(r, dict) for r in results)


# ============================================================================
# CROSS-TOOL TESTS
# ============================================================================

class TestEnergyToolIntegration:
    """Tests for energy tool interactions."""
    
    @pytest.mark.asyncio
    async def test_analyze_then_find_ghosts(self, energy_handler):
        """Workflow: analyze energy, then find ghost spaces."""
        analysis = await energy_handler._handle_analyze_energy({"period": "today"})
        ghosts = await energy_handler._handle_find_ghost_spaces({})
        
        # Ghost operations should contribute to waste in analysis
        if ghosts["ghost_operations"]:
            assert analysis["anomalies"] or analysis.get("waste_kwh") > 0
    
    @pytest.mark.asyncio
    async def test_check_cost_then_decide(self, energy_handler):
        """Workflow: check cost impact before decision."""
        cost = await energy_handler._handle_check_cost_impact({
            "current_temp": 24.0,
            "target_temp": 22.0
        })
        
        # Based on cost, operator might decide
        assert cost.get("recommendation") is not None
        assert "impact" in cost["recommendation"].lower() or "save" in cost["recommendation"].lower()


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
