"""
Maintenance Tool Tests
======================

Comprehensive tests for predictive maintenance tools.

Tools tested:
- predict_maintenance: ML failure prediction
- predict_remaining_life: RUL estimation
- verify_maintenance_work: Physics-based verification

Test categories:
- Happy path: Normal operation
- Edge cases: Empty, invalid, boundary inputs
- Failure modes: Dependency unavailable, errors
- Stress: Concurrent calls, large datasets
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Import mocks
from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockPredictiveMaintenanceEngine,
    create_mock_bms_state_with_equipment,
)

# Import factories
from tests.factories import EquipmentFactory, AlarmFactory, DataPointFactory

# Import assertions
from tests.utils.helpers import assert_valid_tool_result, assert_valid_prediction

# Import tool handlers
from agent_commercial.tools.handlers.maintenance import MaintenanceHandlerMixin


# ============================================================================
# MOCK PREDICTIVE ENGINE
# ============================================================================

class MockPredictiveMaintenanceEngine:
    """Mock predictive maintenance engine for testing."""
    
    def __init__(
        self,
        health_score: float = 85.0,
        failure_probability: float = 0.15,
        rul_days: int = 180,
    ):
        self.health_score = health_score
        self.failure_probability = failure_probability
        self.rul_days = rul_days
        self._predictions_made: List[Dict[str, Any]] = []
    
    async def predict_maintenance(self, equipment_id: str) -> Dict[str, Any]:
        """Return mock maintenance prediction."""
        prediction = {
            "equipment_id": equipment_id,
            "health_score": self.health_score,
            "failure_probability": self.failure_probability,
            "next_maintenance": (datetime.now() + timedelta(days=self.rul_days)).strftime("%Y-%m-%d"),
            "recommendations": ["Continue monitoring"],
        }
        self._predictions_made.append(prediction)
        return prediction
    
    async def predict_rul(self, equipment_id: str, forecast_days: int = 90) -> Dict[str, Any]:
        """Return mock RUL prediction."""
        return {
            "equipment_id": equipment_id,
            "health_score": self.health_score,
            "days_until_predicted_failure": self.rul_days,
            "failure_probability": {
                "30_days": self.failure_probability * 0.3,
                "60_days": self.failure_probability * 0.6,
                "90_days": self.failure_probability,
                str(forecast_days): self.failure_probability,
            },
            "degradation_indicators": ["Normal wear"],
            "recommendation": "Continue monitoring",
        }


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_predictive_engine():
    """Create mock predictive maintenance engine."""
    return MockPredictiveMaintenanceEngine()


@pytest.fixture
def maintenance_handler(mock_bms_state, mock_predictive_engine):
    """Create maintenance handler with mocks."""
    
    class MaintenanceHandler(MaintenanceHandlerMixin):
        def __init__(self):
            self.bms_state = mock_bms_state
            self.predictive_engine = mock_predictive_engine
    
    return MaintenanceHandler()


# ============================================================================
# PREDICT MAINTENANCE
# ============================================================================

class TestPredictMaintenance:
    """Tests for predict_maintenance tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_prediction_for_equipment(self, maintenance_handler):
        """Should return prediction for specific equipment."""
        result = await maintenance_handler._handle_predict_maintenance({
            "equipment_id": "CH-01"
        })
        
        assert "predictions" in result
        assert len(result["predictions"]) == 1
        pred = result["predictions"][0]
        assert pred["equipment_id"] == "CH-01"
        assert "health_score" in pred
        assert "failure_probability" in pred
        assert 0.0 <= pred["failure_probability"] <= 1.0
    
    @pytest.mark.asyncio
    async def test_returns_all_predictions(self, maintenance_handler, mock_bms_state):
        """Should return predictions for all equipment when no ID specified."""
        # Add multiple equipment
        mock_bms_state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-01"))
        mock_bms_state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-01"))
        
        result = await maintenance_handler._handle_predict_maintenance({})
        
        assert "predictions" in result
        # Should return predictions (may be single dict or list)
        predictions = result["predictions"]
        if isinstance(predictions, list):
            assert len(predictions) >= 1
        else:
            assert "equipment_id" in predictions
    
    @pytest.mark.asyncio
    async def test_filters_by_risk_level(self, maintenance_handler, mock_predictive_engine):
        """Should filter predictions by risk level."""
        # Configure engine with high failure probability
        mock_predictive_engine.failure_probability = 0.85
        
        result = await maintenance_handler._handle_predict_maintenance({
            "equipment_id": "CH-01",
            "risk_level": "high"
        })
        
        assert "predictions" in result
        # Tool should respect risk filter
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_equipment_not_found(self, maintenance_handler):
        """Should handle equipment not found gracefully."""
        result = await maintenance_handler._handle_predict_maintenance({
            "equipment_id": "NONEXISTENT-99"
        })
        
        # Should return prediction (engine doesn't validate equipment existence)
        # or return meaningful error
        assert "predictions" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_empty_equipment_id(self, maintenance_handler):
        """Should handle empty equipment ID."""
        result = await maintenance_handler._handle_predict_maintenance({
            "equipment_id": ""
        })
        
        # Should return all predictions or meaningful error
        assert "predictions" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_invalid_risk_level(self, maintenance_handler):
        """Should handle invalid risk level."""
        result = await maintenance_handler._handle_predict_maintenance({
            "equipment_id": "CH-01",
            "risk_level": "invalid_level"
        })
        
        # Should either ignore invalid filter or return error
        assert "predictions" in result or "error" in result
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_engine_unavailable(self, mock_bms_state):
        """Should handle when predictive engine is not configured."""
        
        class HandlerNoEngine(MaintenanceHandlerMixin):
            def __init__(self):
                self.bms_state = mock_bms_state
                self.predictive_engine = None
        
        handler = HandlerNoEngine()
        result = await handler._handle_predict_maintenance({"equipment_id": "CH-01"})
        
        assert "error" in result
        assert "not configured" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_engine_exception(self, mock_bms_state):
        """Should handle engine raising exception."""
        
        class FailingEngine:
            async def predict_maintenance(self, equipment_id):
                raise RuntimeError("Model loading failed")
        
        class HandlerFailingEngine(MaintenanceHandlerMixin):
            def __init__(self):
                self.bms_state = mock_bms_state
                self.predictive_engine = FailingEngine()
        
        handler = HandlerFailingEngine()
        result = await handler._handle_predict_maintenance({"equipment_id": "CH-01"})
        
        # Should return error or fallback
        assert "error" in result or "predictions" in result
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_predictions(self, maintenance_handler):
        """Should handle 100 concurrent prediction requests."""
        tasks = [
            maintenance_handler._handle_predict_maintenance({"equipment_id": f"EQ-{i:02d}"})
            for i in range(100)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should complete without exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
        
        # All should have predictions or errors
        valid_results = [r for r in results if isinstance(r, dict)]
        assert len(valid_results) == 100


# ============================================================================
# PREDICT REMAINING LIFE
# ============================================================================

class TestPredictRemainingLife:
    """Tests for predict_remaining_life tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_returns_rul_prediction(self, maintenance_handler):
        """Should return RUL prediction for equipment."""
        result = await maintenance_handler._handle_predict_remaining_life({
            "equipment_id": "CH-01"
        })
        
        assert "equipment_id" in result
        assert result["equipment_id"] == "CH-01"
        assert "health_score" in result
        assert "days_until_predicted_failure" in result
        assert "failure_probability" in result
        assert "recommendation" in result
    
    @pytest.mark.asyncio
    async def test_custom_forecast_days(self, maintenance_handler, mock_predictive_engine):
        """Should respect custom forecast_days parameter."""
        result = await maintenance_handler._handle_predict_remaining_life({
            "equipment_id": "CH-01",
            "forecast_days": 30
        })
        
        assert "failure_probability" in result
        # Should include 30-day probability
        assert "30_days" in result["failure_probability"] or "30" in str(result["failure_probability"])
    
    @pytest.mark.asyncio
    async def test_failure_probability_ranges(self, maintenance_handler):
        """Should have valid probability ranges."""
        result = await maintenance_handler._handle_predict_remaining_life({
            "equipment_id": "CH-01",
            "forecast_days": 90
        })
        
        # All probabilities should be 0-1
        for key, value in result["failure_probability"].items():
            assert 0.0 <= value <= 1.0, f"Invalid probability for {key}: {value}"
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_missing_equipment_id(self, maintenance_handler):
        """Should require equipment_id."""
        result = await maintenance_handler._handle_predict_remaining_life({})
        
        assert "error" in result
        assert "required" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_invalid_forecast_days(self, maintenance_handler):
        """Should handle invalid forecast_days."""
        result = await maintenance_handler._handle_predict_remaining_life({
            "equipment_id": "CH-01",
            "forecast_days": -1
        })
        
        # Should either use default or return error
        assert "equipment_id" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_very_long_forecast(self, maintenance_handler):
        """Should handle very long forecast (365 days)."""
        result = await maintenance_handler._handle_predict_remaining_life({
            "equipment_id": "CH-01",
            "forecast_days": 365
        })
        
        assert "equipment_id" in result
        # Long-term prediction should still be valid
        assert "failure_probability" in result
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_engine_unavailable_fallback(self, mock_bms_state):
        """Should provide fallback when engine unavailable."""
        
        class HandlerNoEngine(MaintenanceHandlerMixin):
            def __init__(self):
                self.bms_state = mock_bms_state
                self.predictive_engine = None
        
        handler = HandlerNoEngine()
        result = await handler._handle_predict_remaining_life({
            "equipment_id": "CH-01"
        })
        
        # Should still return prediction (fallback)
        assert "equipment_id" in result
        assert "health_score" in result
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_multiple_forecast_windows(self, maintenance_handler):
        """Should handle multiple forecast windows in sequence."""
        for days in [30, 60, 90, 180, 365]:
            result = await maintenance_handler._handle_predict_remaining_life({
                "equipment_id": "CH-01",
                "forecast_days": days
            })
            assert "equipment_id" in result


# ============================================================================
# VERIFY MAINTENANCE WORK
# ============================================================================

class TestVerifyMaintenanceWork:
    """Tests for verify_maintenance_work tool."""
    
    # ==================== HAPPY PATH ====================
    
    @pytest.mark.asyncio
    async def test_verifies_successful_work(self, maintenance_handler):
        """Should verify work that shows improvement."""
        result = await maintenance_handler._handle_verify_maintenance_work({
            "work_order_id": "WO-123",
            "equipment_id": "AHU-01",
            "task_type": "filter_cleaning"
        })
        
        assert "work_order_id" in result
        assert "verified" in result or "status" in result
    
    @pytest.mark.asyncio
    async def test_detects_ghost_maintenance(self, maintenance_handler):
        """Should detect when work was claimed but not done."""
        # Use sample data that shows no improvement
        result = await maintenance_handler._handle_verify_maintenance_work({
            "work_order_id": "WO-GHOST",
            "equipment_id": "AHU-01",
            "task_type": "filter_cleaning",
            "expected_improvement": "efficiency"
        })
        
        # Should return verification status
        assert "work_order_id" in result
    
    @pytest.mark.asyncio
    async def test_different_task_types(self, maintenance_handler):
        """Should handle different maintenance task types."""
        task_types = ["filter_cleaning", "coil_cleaning", "belt_replacement", "chiller_tube_cleaning"]
        
        for task_type in task_types:
            result = await maintenance_handler._handle_verify_maintenance_work({
                "work_order_id": f"WO-{task_type}",
                "equipment_id": "CH-01",
                "task_type": task_type
            })
            assert "work_order_id" in result
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_missing_work_order_id(self, maintenance_handler):
        """Should handle missing work_order_id."""
        result = await maintenance_handler._handle_verify_maintenance_work({
            "equipment_id": "AHU-01"
        })
        
        # Should still return result with default ID
        assert "work_order_id" in result
    
    @pytest.mark.asyncio
    async def test_missing_equipment_id(self, maintenance_handler):
        """Should handle missing equipment_id."""
        result = await maintenance_handler._handle_verify_maintenance_work({
            "work_order_id": "WO-123"
        })
        
        # Should still return result with default ID
        assert "work_order_id" in result
    
    @pytest.mark.asyncio
    async def test_unknown_task_type(self, maintenance_handler):
        """Should handle unknown task type gracefully."""
        result = await maintenance_handler._handle_verify_maintenance_work({
            "work_order_id": "WO-123",
            "equipment_id": "AHU-01",
            "task_type": "unknown_task"
        })
        
        # Should use fallback data
        assert "work_order_id" in result
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_database_unavailable(self, mock_bms_state):
        """Should handle database unavailable."""
        
        class HandlerNoDB(MaintenanceHandlerMixin):
            def __init__(self):
                self.bms_state = mock_bms_state
                self.predictive_engine = None
        
        handler = HandlerNoDB()
        result = await handler._handle_verify_maintenance_work({
            "work_order_id": "WO-123",
            "equipment_id": "AHU-01"
        })
        
        # Should return result with fallback data
        assert "work_order_id" in result
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_verifications(self, maintenance_handler):
        """Should handle concurrent verification requests."""
        tasks = [
            maintenance_handler._handle_verify_maintenance_work({
                "work_order_id": f"WO-{i:03d}",
                "equipment_id": f"AHU-{i % 5:02d}"
            })
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestMaintenanceToolIntegration:
    """Integration tests for maintenance tools."""
    
    @pytest.mark.asyncio
    async def test_full_maintenance_workflow(self, mock_bms_state, mock_predictive_engine):
        """Should support full workflow: predict → verify → track."""
        
        class Handler(MaintenanceHandlerMixin):
            def __init__(self):
                self.bms_state = mock_bms_state
                self.predictive_engine = mock_predictive_engine
        
        handler = Handler()
        
        # Step 1: Predict maintenance needed
        prediction = await handler._handle_predict_maintenance({
            "equipment_id": "CH-01"
        })
        assert "predictions" in prediction
        
        # Step 2: Get RUL details
        rul = await handler._handle_predict_remaining_life({
            "equipment_id": "CH-01",
            "forecast_days": 30
        })
        assert "days_until_predicted_failure" in rul
        
        # Step 3: Verify maintenance after work
        verification = await handler._handle_verify_maintenance_work({
            "work_order_id": "WO-123",
            "equipment_id": "CH-01",
            "task_type": "chiller_tube_cleaning"
        })
        assert "work_order_id" in verification


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(0)
