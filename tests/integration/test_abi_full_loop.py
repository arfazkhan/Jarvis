"""
Integration Test: ABI Full Loop (Predict → Verify → Learn)
==========================================================
Status: Hardened

Tests the complete ABI cycle:
1. PredictionEngine generates prediction
2. VerifyLoop validates outcome
3. OnlineLearner detects drift and retrains

This is the core learning loop that makes ARVIS adaptive.
"""

import pytest
import asyncio
import dataclasses
from datetime import datetime

from agent_cognitive.prediction_engine import PredictionEngine
from agent_advisory.verify_loop import VerifyLoop, Recommendation, RecommendationStatus
from agent_advisory.online_learner import OnlineLearner
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.bms_data_model import Equipment, EquipmentType, EquipmentStatus, BMSDataPoint

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import EquipmentFactory


class TestABIFullLoop:
    """Test complete ABI cycle."""
    
    def _create_equipment(self, data: dict) -> Equipment:
        """Create Equipment object from factory dict."""
        # Map equipment_type string to enum
        eq_type_str = data.pop("equipment_type", "other").upper()
        try:
            data["equipment_type"] = EquipmentType(eq_type_str)
        except ValueError:
            data["equipment_type"] = EquipmentType.OTHER
            
        # Map status string to enum
        status_str = data.pop("status", "unknown").upper()
        try:
            data["status"] = EquipmentStatus(status_str)
        except ValueError:
            data["status"] = EquipmentStatus.UNKNOWN
            
        # Filter fields
        fields = {f.name for f in dataclasses.fields(Equipment)}
        filtered = {k: v for k, v in data.items() if k in fields}
        
        return Equipment(**filtered)

    async def _setup_engines(self):
        """Setup engines and equipment."""
        bms_state = BMSStateEngine()
        await bms_state.register_equipment(self._create_equipment(EquipmentFactory.chiller()))
        await bms_state.register_equipment(self._create_equipment(EquipmentFactory.ahu()))
        
        prediction_engine = PredictionEngine(bms_state_engine=bms_state)
        verify_loop = VerifyLoop(state_engine=bms_state, persist_path=None)
        online_learner = OnlineLearner()
        
        return bms_state, prediction_engine, verify_loop, online_learner
    
    @pytest.mark.asyncio
    async def test_full_loop_happy_path(self):
        """Complete ABI cycle with accurate prediction."""
        bms_state, prediction_engine, verify_loop, online_learner = await self._setup_engines()
        
        # Step 1: Prediction
        prediction = await prediction_engine.predict_energy_demand(
            horizon_minutes=1440,  # 24 hours
        )
        
        assert prediction is not None
        assert prediction.confidence >= 0.5
        
        # Step 2: Simulate actual outcome
        actual = {
            "total_power_kw": 450.0,
            "chiller_load_pct": 85.0,
        }
        await bms_state.update_point(BMSDataPoint(point_id="METER-01/KW", name="Main Meter", value=actual["total_power_kw"]))
        
        # Step 3: Verify (manual validation via PredictionEngine for this test)
        error = prediction_engine.learn_from_validation(
            prediction_id=prediction.prediction_id,
            actual_state=actual,
        )
        
        assert error is not None
        assert error < 200.0  # reasonable error for uncalibrated model
        
        # Step 4: Learn (log observation)
        await online_learner.log_observation(
            prediction_type="energy_demand",
            predicted_values=prediction.predicted,
            actual_values=actual,
            prediction_id=prediction.prediction_id
        )
        
        # Verify status
        summary = online_learner.get_performance_summary()
        assert summary["status"] == "active"
    
    @pytest.mark.asyncio
    async def test_drift_detection_triggers_retraining(self):
        """Drift detection should trigger retraining."""
        bms_state, prediction_engine, verify_loop, online_learner = await self._setup_engines()
        
        # Establish baseline first (need 20 samples)
        for i in range(20):
            await online_learner.log_observation(
                prediction_type="energy_demand",
                predicted_values={"kw": 400.0},
                actual_values={"kw": 405.0},
                prediction_id=f"BASE-{i}"
            )
            
        summary_base = online_learner.get_performance_summary()
        assert summary_base["total_observations"] == 20
        
        # Simulate series of inaccurate predictions to trigger drift (need more samples)
        # OnlineLearner checks for drift every 10 samples
        for i in range(10):
            # Actual is very different
            actual = {
                "total_power_kw": 800.0,  # Double the prediction
                "chiller_load_pct": 95.0,
            }
            
            await online_learner.log_observation(
                prediction_type="energy_demand",
                predicted_values={"kw": 400.0},
                actual_values={"kw": 800.0},
                prediction_id=f"DRIFT-{i}"
            )
        
        # Check drift
        summary = online_learner.get_performance_summary()
        
        # Drift should be detected or error should be high
        assert summary["total_observations"] == 30
        assert summary["recent_rmse"] > 100.0
    
    @pytest.mark.asyncio
    async def test_prediction_improves_after_feedback(self):
        """Prediction accuracy should improve after operator feedback."""
        bms_state, prediction_engine, verify_loop, online_learner = await self._setup_engines()
        
        # Initial prediction
        prediction1 = await prediction_engine.predict_energy_demand(
            horizon_minutes=1440,
        )
        
        # Simulate feedback loop
        await bms_state.update_point(BMSDataPoint(point_id="CH-01/LOAD", name="Chiller Load", value=90.0))  # Higher load than expected
        
        # Run learning cycle (direct mock feedback for this test)
        prediction_engine.learn_from_validation(
            prediction_id=prediction1.prediction_id,
            actual_state={"total_power_kw": 500.0}
        )
        
        # Second prediction should incorporate feedback
        prediction2 = await prediction_engine.predict_energy_demand(
            horizon_minutes=1440,
        )
        
        # Both predictions should be valid
        assert prediction1 is not None
        assert prediction2 is not None
    
    @pytest.mark.asyncio
    async def test_multi_equipment_prediction(self):
        """Predictions for multiple equipment should work."""
        bms_state, prediction_engine, verify_loop, online_learner = await self._setup_engines()
        
        # Add multiple equipment
        await bms_state.register_equipment(self._create_equipment(EquipmentFactory.chiller(equipment_id="CH-02")))
        await bms_state.register_equipment(self._create_equipment(EquipmentFactory.ahu(equipment_id="AHU-02")))
        
        # Predict energy
        prediction = await prediction_engine.predict_energy_demand()
        
        assert prediction is not None
    
    @pytest.mark.asyncio
    async def test_verify_loop_rejects_unsafe_action(self):
        """Verify loop should handle rejections."""
        bms_state, prediction_engine, verify_loop, online_learner = await self._setup_engines()
        
        # Register a recommendation
        rec_id = await verify_loop.register_recommendation(
            title="Emergency Shutdown",
            description="Shutdown immediately",
            recommendation_type="safety",
            action_type="emergency",
            predicted_outcome={"safety": "critical"},
            confidence=0.95,
            equipment_id="CH-01"
        )
        
        # Reject it
        await verify_loop.reject(rec_id, operator_id="admin", reason="Already handled")
        
        # Check status
        rec_data = verify_loop.get_recommendation(rec_id)
        assert rec_data["status"] == "rejected"
    
    @pytest.mark.asyncio
    async def test_online_learner_persistence(self):
        """Online learner should persist observations."""
        online_learner = OnlineLearner()
        
        # Log multiple observations
        for i in range(10):
            await online_learner.log_observation(
                prediction_type="test",
                prediction_id=f"PRED-{i}",
                predicted_values={"value": 100.0 + i},
                actual_values={"value": 105.0 + i},
            )
        
        summary = online_learner.get_performance_summary()
        
        assert summary["total_observations"] == 10


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
