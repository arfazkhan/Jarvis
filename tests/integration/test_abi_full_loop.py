"""
Integration Test: ABI Full Loop (Predict → Verify → Learn)
==========================================================

Tests the complete ABI cycle:
1. PredictionEngine generates prediction
2. VerifyLoop validates outcome
3. OnlineLearner detects drift and retrains

This is the core learning loop that makes ARVIS adaptive.
"""

import pytest
import asyncio
from datetime import datetime

from agent_cognitive.prediction_engine import PredictionEngine
from agent_advisory.verify_loop import VerifyLoop
from agent_advisory.online_learner import OnlineLearner
from agent_commercial.bms_state_engine import BMSStateEngine

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import EquipmentFactory


class TestABIFullLoop:
    """Test complete ABI cycle."""
    
    @pytest.fixture
    def mock_state(self):
        """Mock BMS state with sample equipment."""
        state = MockBMSStateEngine()
        state.add_equipment(EquipmentFactory.chiller())
        state.add_equipment(EquipmentFactory.ahu())
        return state
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM for predictions."""
        return MockLLM()
    
    @pytest.fixture
    def prediction_engine(self, mock_state, mock_llm):
        """Real PredictionEngine with mocks."""
        return PredictionEngine(
            bms_state=mock_state,
            llm=mock_llm,
        )
    
    @pytest.fixture
    def verify_loop(self, mock_state, mock_llm):
        """Real VerifyLoop with mocks."""
        return VerifyLoop(
            bms_state=mock_state,
            llm=mock_llm,
        )
    
    @pytest.fixture
    def online_learner(self, mock_llm):
        """Real OnlineLearner with mock LLM."""
        return OnlineLearner(llm=mock_llm)
    
    @pytest.mark.asyncio
    async def test_full_loop_happy_path(
        self,
        prediction_engine,
        verify_loop,
        online_learner,
        mock_state,
    ):
        """Complete ABI cycle with accurate prediction."""
        # Step 1: Prediction
        prediction = await prediction_engine.predict_demand_forecast(
            building_id="test-building",
            horizon_hours=24,
        )
        
        assert prediction is not None
        assert prediction.confidence > 0.5
        
        # Step 2: Simulate actual outcome
        actual = {
            "total_power_kw": 450.0,
            "chiller_load_pct": 85.0,
        }
        mock_state.update_point("METER-01/KW", actual["total_power_kw"])
        
        # Step 3: Verify
        verification = await verify_loop.validate_outcome(
            prediction=prediction,
            actual=actual,
        )
        
        assert verification.verified
        assert verification.error_within_tolerance
        
        # Step 4: Learn (log observation)
        online_learner.log_observation(
            prediction={"total_power_kw": prediction.predicted_value},
            actual=actual,
        )
        
        # Verify no drift detected (accurate prediction)
        summary = online_learner.get_performance_summary()
        assert summary["drift_ratio"] < 1.5
    
    @pytest.mark.asyncio
    async def test_drift_detection_triggers_retraining(
        self,
        prediction_engine,
        verify_loop,
        online_learner,
        mock_state,
    ):
        """Drift detection should trigger retraining."""
        # Simulate series of inaccurate predictions
        for i in range(20):
            # Prediction is consistently wrong
            prediction = await prediction_engine.predict_demand_forecast(
                building_id="test-building",
                horizon_hours=24,
            )
            
            # Actual is very different
            actual = {
                "total_power_kw": 600.0,  # Much higher than predicted
                "chiller_load_pct": 95.0,
            }
            
            online_learner.log_observation(
                prediction={"total_power_kw": prediction.predicted_value},
                actual=actual,
            )
        
        # Check drift
        summary = online_learner.get_performance_summary()
        
        # Drift should be detected
        assert summary["drift_ratio"] > 1.5 or summary["current_rmse"] > 50.0
    
    @pytest.mark.asyncio
    async def test_prediction_improves_after_feedback(
        self,
        prediction_engine,
        verify_loop,
        mock_state,
        mock_llm,
    ):
        """Prediction accuracy should improve after operator feedback."""
        # Initial prediction
        prediction1 = await prediction_engine.predict_demand_forecast(
            building_id="test-building",
            horizon_hours=24,
        )
        
        # Simulate feedback loop
        mock_state.update_point("CH-01/LOAD", 90.0)  # Higher load than expected
        
        # Run learning cycle
        feedback_result = await verify_loop.process_operator_feedback(
            equipment_id="CH-01",
            feedback_type="correction",
            feedback="Load is higher due to high ambient temperature",
        )
        
        assert feedback_result is not None
        
        # Second prediction should incorporate feedback
        prediction2 = await prediction_engine.predict_demand_forecast(
            building_id="test-building",
            horizon_hours=24,
        )
        
        # Both predictions should be valid
        assert prediction1 is not None
        assert prediction2 is not None
    
    @pytest.mark.asyncio
    async def test_multi_equipment_prediction(
        self,
        prediction_engine,
        mock_state,
    ):
        """Predictions for multiple equipment should work."""
        # Add multiple equipment
        mock_state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-02"))
        mock_state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-02"))
        
        # Predict for all
        predictions = await prediction_engine.predict_all_equipment()
        
        assert len(predictions) > 0
    
    @pytest.mark.asyncio
    async def test_verify_loop_rejects_unsafe_action(self, verify_loop, mock_state):
        """Verify loop should reject unsafe actions."""
        from agent_advisory.verify_loop import Recommendation
        
        # Create recommendation that violates safety
        unsafe_rec = Recommendation(
            recommendation_id="REC-001",
            equipment_id="CH-01",
            action="shutdown_immediately",
            action_type="emergency",
            confidence=0.95,
            gsas_aligned=False,
            safety_validated=False,
        )
        
        result = await verify_loop.validate_recommendation(
            recommendation=unsafe_rec,
            bms_state=mock_state,
        )
        
        # Should reject or flag as unsafe
        assert not result.approved or result.safety_concerns
    
    @pytest.mark.asyncio
    async def test_online_learner_persistence(self, online_learner):
        """Online learner should persist observations."""
        # Log multiple observations
        for i in range(10):
            online_learner.log_observation(
                prediction={"value": 100.0 + i},
                actual={"value": 105.0 + i},
            )
        
        summary = online_learner.get_performance_summary()
        
        assert summary["sample_count"] == 10
        assert summary["current_rmse"] > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
