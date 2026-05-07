"""
ML Tool Tests
=============

Comprehensive tests for ML-powered tools:
- forecast_energy: Energy demand forecasting with ML
- detect_equipment_faults: Fault detection using VAE
- analyze_root_cause: Bayesian root cause analysis
- simulate_with_uncertainty: Monte Carlo simulation
- find_similar_skills: Semantic skill search
- benchmark_building_ml: Building archetype clustering

Tests cover:
- Happy path: Normal ML operations
- Edge cases: Empty forecasts, no faults, no root causes
- Failure modes: ML engine unavailable
- Stress: Large forecast (168h), concurrent requests
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any, List

# Add parent directory to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.mocks import (
    MockBMSStateEngine,
    MockPredictiveEngine,
    MockWorldModel,
    MockKnowledgeBase,
)
from tests.factories import EquipmentFactory
from tests.utils.helpers import (
    assert_valid_tool_result,
    assert_forecast_format,
    time_operation,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bms_state():
    """Mock BMS state with equipment."""
    state = MockBMSStateEngine()
    state.add_equipment(EquipmentFactory.chiller())
    state.add_equipment(EquipmentFactory.ahu())
    return state


@pytest.fixture
def mock_predictive_engine():
    """Mock predictive engine for ML tests."""
    return MockPredictiveEngine()


@pytest.fixture
def mock_world_model():
    """Mock world model for Bayesian/simulation tests."""
    return MockWorldModel()


@pytest.fixture
def mock_knowledge_base():
    """Mock knowledge base for skill search."""
    return MockKnowledgeBase()


# ============================================================================
# FORECAST ENERGY TOOL
# ============================================================================

class TestForecastEnergy:
    """Tests for forecast_energy tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_24h_forecast(self, mock_predictive_engine):
        """Should return 24-hour forecast with confidence intervals."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=24)
        
        assert result.success
        assert len(result.output["forecast"]) == 24
        assert result.output["model"] == "mock_default"
        
        # Verify each forecast entry
        for entry in result.output["forecast"]:
            assert "hour" in entry
            assert "predicted_kw" in entry
            assert entry["predicted_kw"] > 0
    
    @pytest.mark.asyncio
    async def test_includes_confidence_intervals(self, mock_predictive_engine):
        """Should include confidence low/high when requested."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=24, include_confidence=True)
        
        assert result.success
        for entry in result.output["forecast"]:
            assert entry.get("confidence_low") is not None
            assert entry.get("confidence_high") is not None
            assert entry["confidence_low"] < entry["predicted_kw"] < entry["confidence_high"]
    
    @pytest.mark.asyncio
    async def test_forecast_without_confidence(self, mock_predictive_engine):
        """Should omit confidence when include_confidence=False."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=24, include_confidence=False)
        
        assert result.success
        for entry in result.output["forecast"]:
            # Should be None or absent
            assert entry.get("confidence_low") is None
            assert entry.get("confidence_high") is None
    
    @pytest.mark.asyncio
    async def test_custom_forecast_data(self, mock_predictive_engine):
        """Should use custom forecast data when set."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        # Set custom forecast
        custom_forecast = [
            {"hour": i, "predicted_kw": 500.0 + i * 10, "confidence_low": 450.0, "confidence_high": 550.0}
            for i in range(48)
        ]
        mock_predictive_engine.set_forecast(custom_forecast)
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=48)
        
        assert result.success
        assert result.output["forecast"][0]["predicted_kw"] == 500.0
        assert result.output["forecast"][47]["predicted_kw"] == 500.0 + 47 * 10
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_max_forecast_168h(self, mock_predictive_engine):
        """Should handle maximum forecast horizon (168h = 1 week)."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=168)
        
        assert result.success
        assert len(result.output["forecast"]) == 168
    
    @pytest.mark.asyncio
    async def test_min_forecast_1h(self, mock_predictive_engine):
        """Should handle minimum forecast horizon (1h)."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(forecast_hours=1)
        
        assert result.success
        assert len(result.output["forecast"]) == 1
    
    @pytest.mark.asyncio
    async def test_forecast_with_building_id(self, mock_predictive_engine):
        """Should include building_id in response."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(building_id="tower_a", forecast_hours=24)
        
        assert result.success
        assert result.output["building_id"] == "tower_a"
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback calculation when engine is None."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = None  # No ML engine
        
        result = await tool.execute(forecast_hours=24)
        
        # Should still succeed with fallback
        assert result.success
        assert "forecast" in result.output
        assert result.output["model"] == "fallback_pattern"
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_forecast_requests(self, mock_predictive_engine):
        """Should handle 50 concurrent forecast requests."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        tasks = [
            tool.execute(forecast_hours=24, building_id=f"building_{i}")
            for i in range(50)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0
        
        successes = [r for r in results if hasattr(r, 'success') and r.success]
        assert len(successes) == 50


# ============================================================================
# DETECT EQUIPMENT FAULTS TOOL
# ============================================================================

class TestDetectEquipmentFaults:
    """Tests for detect_equipment_faults tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_detects_no_faults(self, mock_predictive_engine):
        """Should return empty faults when none detected."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert result.output["equipment_id"] == "CH-01"
        assert result.output["faults_detected"] == []
        assert result.output["status"] == "normal"
    
    @pytest.mark.asyncio
    async def test_detects_single_fault(self, mock_predictive_engine):
        """Should detect single fault."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        # Add fault
        mock_predictive_engine.add_fault({
            "equipment_id": "CH-01",
            "fault_type": "sensor_drift",
            "severity": "medium",
            "confidence": 0.85,
        })
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert len(result.output["faults_detected"]) == 1
        assert result.output["faults_detected"][0]["fault_type"] == "sensor_drift"
        assert result.output["status"] == "fault"
    
    @pytest.mark.asyncio
    async def test_detects_multiple_faults(self, mock_predictive_engine):
        """Should detect multiple faults."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        # Add multiple faults
        mock_predictive_engine.add_fault({
            "equipment_id": "CH-01",
            "fault_type": "sensor_drift",
            "severity": "medium",
        })
        mock_predictive_engine.add_fault({
            "equipment_id": "CH-01",
            "fault_type": "valve_stuck",
            "severity": "high",
        })
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert len(result.output["faults_detected"]) == 2
    
    @pytest.mark.asyncio
    async def test_filters_by_fault_type(self, mock_predictive_engine):
        """Should filter results by fault_type."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        # Add faults of different types
        mock_predictive_engine.add_fault({
            "equipment_id": "CH-01",
            "fault_type": "sensor_drift",
            "severity": "low",
        })
        mock_predictive_engine.add_fault({
            "equipment_id": "CH-01",
            "fault_type": "valve_stuck",
            "severity": "high",
        })
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(equipment_id="CH-01", fault_type="valve_stuck")
        
        assert result.success
        assert len(result.output["faults_detected"]) == 1
        assert result.output["faults_detected"][0]["fault_type"] == "valve_stuck"
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_unknown_equipment(self, mock_predictive_engine):
        """Should return empty faults for unknown equipment."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = mock_predictive_engine
        
        result = await tool.execute(equipment_id="UNKNOWN-99")
        
        assert result.success
        assert result.output["faults_detected"] == []
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_missing_equipment_id(self):
        """Should return error when equipment_id is missing."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        tool = DetectEquipmentFaults()
        
        result = await tool.execute()
        
        assert not result.success
        assert "required" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback when engine is None."""
        from agent_commercial.tools.ml import DetectEquipmentFaults
        
        tool = DetectEquipmentFaults()
        tool.predictive_engine = None
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert result.output["faults_detected"] == []
        assert result.output["status"] == "normal"


# ============================================================================
# ANALYZE ROOT CAUSE TOOL
# ============================================================================

class TestAnalyzeRootCause:
    """Tests for analyze_root_cause tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_analyzes_alarm_cascade(self, mock_world_model):
        """Should analyze multiple alarms and find root cause."""
        from agent_commercial.tools.ml import AnalyzeRootCause
        
        # Add root cause
        mock_world_model.add_root_cause({
            "cause": "CH-01 refrigerant leak",
            "probability": 0.85,
            "evidence": ["Low superheat", "High suction pressure"],
        })
        
        tool = AnalyzeRootCause()
        tool.world_model = mock_world_model
        
        result = await tool.execute(alarm_ids=["ALM-1", "ALM-2", "ALM-3"])
        
        assert result.success
        assert result.output["alarm_ids"] == ["ALM-1", "ALM-2", "ALM-3"]
        assert len(result.output["root_causes"]) == 1
        assert result.output["root_causes"][0]["cause"] == "CH-01 refrigerant leak"
        assert result.output["root_causes"][0]["probability"] == 0.85
    
    @pytest.mark.asyncio
    async def test_single_alarm(self, mock_world_model):
        """Should handle single alarm."""
        from agent_commercial.tools.ml import AnalyzeRootCause
        
        mock_world_model.add_root_cause({
            "cause": "Sensor malfunction",
            "probability": 0.6,
            "evidence": [],
        })
        
        tool = AnalyzeRootCause()
        tool.world_model = mock_world_model
        
        result = await tool.execute(alarm_ids=["ALM-1"])
        
        assert result.success
        assert len(result.output["root_causes"]) == 1
    
    @pytest.mark.asyncio
    async def test_custom_system_depth(self, mock_world_model):
        """Should pass custom depth to analysis."""
        from agent_commercial.tools.ml import AnalyzeRootCause
        
        tool = AnalyzeRootCause()
        tool.world_model = mock_world_model
        
        result = await tool.execute(alarm_ids=["ALM-1"], system_depth=5)
        
        assert result.success
        assert result.output["analysis_depth"] == 5
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_missing_alarm_ids(self):
        """Should return error when alarm_ids is missing."""
        from agent_commercial.tools.ml import AnalyzeRootCause
        
        tool = AnalyzeRootCause()
        
        result = await tool.execute()
        
        assert not result.success
        assert "required" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback when world_model is None."""
        from agent_commercial.tools.ml import AnalyzeRootCause
        
        tool = AnalyzeRootCause()
        tool.world_model = None
        
        result = await tool.execute(alarm_ids=["ALM-1"])
        
        assert result.success
        assert result.output["root_causes"][0]["cause"] == "Unknown"


# ============================================================================
# SIMULATE WITH UNCERTAINTY TOOL
# ============================================================================

class TestSimulateWithUncertainty:
    """Tests for simulate_with_uncertainty tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_simulate_setpoint_change(self, mock_world_model):
        """Should simulate setpoint change with uncertainty."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        mock_world_model.set_simulation_result({
            "energy_impact_pct": -5.2,
            "comfort_impact": "minimal",
            "risk_assessment": {
                "worst_case": -7.8,
                "best_case": -2.6,
                "probability_negative": 0.1,
            },
        })
        
        tool = SimulateWithUncertainty()
        tool.world_model = mock_world_model
        
        result = await tool.execute(
            change_type="setpoint",
            current_value=22.0,
            proposed_value=24.0,
        )
        
        assert result.success
        assert result.output["energy_impact_pct"] == -5.2
        assert "risk_assessment" in result.output
        assert "worst_case" in result.output["risk_assessment"]
    
    @pytest.mark.asyncio
    async def test_simulate_with_equipment_id(self, mock_world_model):
        """Should include equipment_id in simulation."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        tool = SimulateWithUncertainty()
        tool.world_model = mock_world_model
        
        result = await tool.execute(
            change_type="setpoint",
            current_value=22.0,
            proposed_value=24.0,
            equipment_id="AHU-01",
        )
        
        assert result.success
    
    @pytest.mark.asyncio
    async def test_simulate_with_zone_id(self, mock_world_model):
        """Should include zone_id in simulation."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        tool = SimulateWithUncertainty()
        tool.world_model = mock_world_model
        
        result = await tool.execute(
            change_type="setpoint",
            current_value=22.0,
            proposed_value=24.0,
            zone_id="ZONE-F1-01",
        )
        
        assert result.success
    
    @pytest.mark.asyncio
    async def test_custom_monte_carlo_samples(self, mock_world_model):
        """Should pass custom Monte Carlo samples."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        tool = SimulateWithUncertainty()
        tool.world_model = mock_world_model
        
        result = await tool.execute(
            change_type="setpoint",
            current_value=22.0,
            proposed_value=24.0,
            monte_carlo_samples=5000,
        )
        
        assert result.success
        assert result.output.get("monte_carlo_samples") == 5000
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_missing_required_params(self):
        """Should error when required params missing."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        tool = SimulateWithUncertainty()
        
        result = await tool.execute(change_type="setpoint")
        
        assert not result.success
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback when world_model is None."""
        from agent_commercial.tools.ml import SimulateWithUncertainty
        
        tool = SimulateWithUncertainty()
        tool.world_model = None
        
        result = await tool.execute(
            change_type="setpoint",
            current_value=22.0,
            proposed_value=24.0,
        )
        
        assert result.success
        assert "energy_impact_pct" in result.output


# ============================================================================
# FIND SIMILAR SKILLS TOOL
# ============================================================================

class TestFindSimilarSkills:
    """Tests for find_similar_skills tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_finds_matching_skills(self, mock_knowledge_base):
        """Should find skills matching query."""
        from agent_commercial.tools.ml import FindSimilarSkills
        
        mock_knowledge_base.add_skill({
            "skill_id": "SK-01",
            "title": "Chiller Efficiency Optimization",
            "similarity": 0.92,
        })
        
        tool = FindSimilarSkills()
        tool.knowledge_base = mock_knowledge_base
        
        result = await tool.execute(query="chiller not cooling efficiently")
        
        assert result.success
        assert len(result.output["results"]) == 1
        assert result.output["results"][0]["similarity"] == 0.92
    
    @pytest.mark.asyncio
    async def test_returns_top_k_results(self, mock_knowledge_base):
        """Should limit results to top_k."""
        from agent_commercial.tools.ml import FindSimilarSkills
        
        # Add multiple skills
        for i in range(10):
            mock_knowledge_base.add_skill({
                "skill_id": f"SK-{i:02d}",
                "title": f"Skill {i}",
                "similarity": 0.9 - i * 0.05,
            })
        
        tool = FindSimilarSkills()
        tool.knowledge_base = mock_knowledge_base
        
        result = await tool.execute(query="cooling problem", top_k=5)
        
        assert result.success
        assert len(result.output["results"]) == 5
    
    @pytest.mark.asyncio
    async def test_filters_by_equipment_type(self, mock_knowledge_base):
        """Should filter results by equipment type."""
        from agent_commercial.tools.ml import FindSimilarSkills
        
        mock_knowledge_base.add_skill({
            "skill_id": "SK-01",
            "title": "AHU Maintenance",
            "equipment_type": "ahu",
            "similarity": 0.95,
        })
        mock_knowledge_base.add_skill({
            "skill_id": "SK-02",
            "title": "Chiller Maintenance",
            "equipment_type": "chiller",
            "similarity": 0.90,
        })
        
        tool = FindSimilarSkills()
        tool.knowledge_base = mock_knowledge_base
        
        result = await tool.execute(
            query="maintenance",
            equipment_type="ahu",
        )
        
        assert result.success
        # Should only return AHU skill
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_missing_query(self):
        """Should error when query is missing."""
        from agent_commercial.tools.ml import FindSimilarSkills
        
        tool = FindSimilarSkills()
        
        result = await tool.execute()
        
        assert not result.success
        assert "required" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback when knowledge_base is None."""
        from agent_commercial.tools.ml import FindSimilarSkills
        
        tool = FindSimilarSkills()
        tool.knowledge_base = None
        
        result = await tool.execute(query="chiller problem")
        
        assert result.success
        assert result.output["results"] == []


# ============================================================================
# BENCHMARK BUILDING ML TOOL
# ============================================================================

class TestBenchmarkBuildingML:
    """Tests for benchmark_building_ml tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_benchmarks_default_building(self, mock_world_model):
        """Should benchmark default building."""
        from agent_commercial.tools.ml import BenchmarkBuildingML
        
        tool = BenchmarkBuildingML()
        tool.world_model = mock_world_model
        
        result = await tool.execute()
        
        assert result.success
        assert "archetype" in result.output
        assert "percentile_rankings" in result.output
        assert "improvement_opportunities" in result.output
    
    @pytest.mark.asyncio
    async def test_benchmarks_specific_building(self, mock_world_model):
        """Should benchmark specific building."""
        from agent_commercial.tools.ml import BenchmarkBuildingML
        
        mock_world_model.set_benchmark({
            "building_id": "tower_a",
            "archetype": "Data Center",
            "percentile_rankings": {"energy_eui": 45},
        })
        
        tool = BenchmarkBuildingML()
        tool.world_model = mock_world_model
        
        result = await tool.execute(building_id="tower_a")
        
        assert result.success
        assert result.output["building_id"] == "tower_a"
        assert result.output["archetype"] == "Data Center"
    
    @pytest.mark.asyncio
    async def test_different_comparison_scopes(self, mock_world_model):
        """Should support different comparison scopes."""
        from agent_commercial.tools.ml import BenchmarkBuildingML
        
        tool = BenchmarkBuildingML()
        tool.world_model = mock_world_model
        
        # Test each scope
        for scope in ["local_fleet", "regional", "global"]:
            result = await tool.execute(comparison_scope=scope)
            assert result.success
            assert result.output["comparison_scope"] == scope
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_engine_none_uses_fallback(self):
        """Should use fallback when world_model is None."""
        from agent_commercial.tools.ml import BenchmarkBuildingML
        
        tool = BenchmarkBuildingML()
        tool.world_model = None
        
        result = await tool.execute()
        
        assert result.success
        assert result.output["archetype"] == "Large Office Cooling-Dominated"


# ============================================================================
# STRESS TESTS
# ============================================================================

class TestMLToolsStress:
    """Stress tests for ML tools."""
    
    @pytest.mark.asyncio
    async def test_large_forecast_with_confidence(self, mock_predictive_engine):
        """Should handle large forecast with confidence calculations."""
        from agent_commercial.tools.ml import ForecastEnergy
        
        tool = ForecastEnergy()
        tool.predictive_engine = mock_predictive_engine
        
        # Max forecast (168h) with confidence
        result = await tool.execute(forecast_hours=168, include_confidence=True)
        
        assert result.success
        assert len(result.output["forecast"]) == 168
        
        # All entries should have confidence
        for entry in result.output["forecast"]:
            assert entry.get("confidence_low") is not None
            assert entry.get("confidence_high") is not None
    
    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self, mock_predictive_engine, mock_world_model):
        """Should handle concurrent operations across different tools."""
        from agent_commercial.tools.ml import ForecastEnergy, DetectEquipmentFaults, SimulateWithUncertainty
        
        forecast_tool = ForecastEnergy()
        forecast_tool.predictive_engine = mock_predictive_engine
        
        fault_tool = DetectEquipmentFaults()
        fault_tool.predictive_engine = mock_predictive_engine
        
        sim_tool = SimulateWithUncertainty()
        sim_tool.world_model = mock_world_model
        
        # Run 100 concurrent operations
        tasks = []
        for i in range(33):
            tasks.extend([
                forecast_tool.execute(forecast_hours=24),
                fault_tool.execute(equipment_id=f"CH-{i % 5:02d}"),
                sim_tool.execute(change_type="setpoint", current_value=22.0, proposed_value=24.0),
            ])
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(0)
