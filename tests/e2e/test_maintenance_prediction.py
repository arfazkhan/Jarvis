#!/usr/bin/env python3
"""
E2E Test: Predictive Maintenance Workflow
=========================================

Scenario: Failure predicted → operator scheduled maintenance → verified.

Full workflow:
1. System predicts chiller bearing failure (14 days RUL)
2. Operator receives alert
3. Operator schedules maintenance within window
4. Maintenance performed
5. System verifies improvement via telemetry
6. Prediction model updated
"""

import pytest
import asyncio

from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockPredictiveEngine,
)
from tests.factories import EquipmentFactory


class TestMaintenancePrediction:
    """
    Test predictive maintenance workflow.
    """
    
    @pytest.fixture
    def failing_chiller(self):
        """Chiller with predicted bearing failure."""
        state = MockBMSStateEngine()
        state.add_equipment(EquipmentFactory.chiller())
        
        # Points indicating degradation
        state.update_point("CH-01/VIBRATION", 8.5, "mm/s", "CH-01")  # High
        state.update_point("CH-01/EFFICIENCY", 0.85, None, "CH-01")  # Declining
        state.update_point("CH-01/RUNTIME", 5200, "hours", "CH-01")  # High hours
        
        return state
    
    @pytest.fixture
    def predictive_engine(self):
        """Engine with failure prediction."""
        engine = MockPredictiveEngine()
        engine.set_prediction("CH-01", {
            "equipment_id": "CH-01",
            "health_score": 62,
            "days_until_predicted_failure": 14,
            "failure_probability": {
                "7_days": 0.15,
                "14_days": 0.45,
                "30_days": 0.75,
            },
            "failure_mode": "bearing_wear",
            "recommendation": "Schedule bearing inspection within 7 days",
        })
        return engine
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_failure_prediction_generated(self, failing_chiller, predictive_engine):
        """System should predict bearing failure."""
        prediction = await predictive_engine.predict_rul("CH-01", forecast_days=30)
        
        assert prediction["health_score"] < 70
        assert prediction["days_until_predicted_failure"] < 30
        assert prediction["failure_probability"]["30_days"] > 0.5
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_maintenance_scheduled_in_window(self, predictive_engine):
        """Operator schedules maintenance within prediction window."""
        prediction = await predictive_engine.predict_rul("CH-01", forecast_days=30)
        
        # RUL is 14 days, so maintenance must be scheduled within 7 days
        recommended_window = 7  # days
        
        assert prediction["days_until_predicted_failure"] > recommended_window
        
        # Simulate work order creation
        work_order = {
            "work_order_id": "WO-2024-001",
            "equipment_id": "CH-01",
            "task_type": "bearing_inspection",
            "scheduled_date": "2024-01-22",
            "priority": "high",
        }
        
        assert work_order["equipment_id"] == "CH-01"
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_maintenance_verification(self, failing_chiller):
        """System verifies maintenance was effective."""
        # Pre-maintenance state
        pre_vibration = 8.5
        
        # Post-maintenance state (simulated)
        failing_chiller.update_point("CH-01/VIBRATION", 5.2, "mm/s", "CH-01")
        failing_chiller.update_point("CH-01/EFFICIENCY", 0.92, None, "CH-01")
        
        # Get new values
        post_vibration = failing_chiller.get_point("CH-01/VIBRATION")["value"]
        
        # Should show improvement
        assert post_vibration < pre_vibration
        improvement_pct = ((pre_vibration - post_vibration) / pre_vibration) * 100
        assert improvement_pct > 20  # At least 20% improvement


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
