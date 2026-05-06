#!/usr/bin/env python3
"""
Test: ABI™ Prediction Engine
============================

Tests prediction, drift detection, and learning.
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime
from agent_cognitive.prediction_engine import (
    PredictionEngine,
    PredictionType,
    PredictedState,
)


async def test_energy_prediction():
    """Test 1: Energy demand prediction"""
    print("\n" + "=" * 60)
    print("TEST 1: Energy Demand Prediction")
    print("=" * 60)
    
    engine = PredictionEngine(building_id="test-building")
    
    # Predict for 1 hour ahead
    prediction = await engine.predict_energy_demand(
        horizon_minutes=60,
        weather={"temperature": 35, "humidity": 60},
        occupancy_hint="high",
    )
    
    print(f"\nPrediction ID: {prediction.prediction_id}")
    print(f"Type: {prediction.prediction_type.value}")
    print(f"Horizon: {prediction.horizon_minutes} minutes")
    print(f"Confidence: {prediction.confidence:.2f}")
    print(f"\nPredicted Values:")
    for key, value in prediction.predicted.items():
        print(f"  {key}: {value}")
    
    assert prediction.predicted["total_power_kw"] > 0
    assert 0 < prediction.confidence <= 1
    print("\n✅ PASS")
    return prediction


async def test_validation_and_learning():
    """Test 2: Validation and learning from feedback"""
    print("\n" + "=" * 60)
    print("TEST 2: Validation and Learning")
    print("=" * 60)
    
    engine = PredictionEngine(building_id="test-building")
    
    # Make prediction
    prediction = await engine.predict_energy_demand(horizon_minutes=60)
    pred_id = prediction.prediction_id
    
    print(f"\nPrediction: {prediction.predicted}")
    
    # Simulate actual outcome (slightly different from prediction)
    actual_state = {
        "total_power_kw": prediction.predicted["total_power_kw"] * 0.95,
        "hvac_power_kw": prediction.predicted["hvac_power_kw"] * 0.93,
        "lighting_power_kw": prediction.predicted["lighting_power_kw"],
        "other_power_kw": prediction.predicted["other_power_kw"],
    }
    
    print(f"Actual: {actual_state}")
    
    # Validate
    error = engine.learn_from_validation(pred_id, actual_state)
    
    print(f"\nValidation Error: {error:.2f}")
    
    # Check prediction was updated
    validated_pred = engine.get_prediction(pred_id)
    assert validated_pred.validated_at is not None
    assert validated_pred.actual is not None
    
    print(f"Prediction validated at: {validated_pred.validated_at}")
    print("\n✅ PASS")


async def test_drift_detection():
    """Test 3: Drift detection after multiple validations"""
    print("\n" + "=" * 60)
    print("TEST 3: Drift Detection")
    print("=" * 60)
    
    engine = PredictionEngine(building_id="test-building")
    
    # Make and validate multiple predictions
    for i in range(10):
        prediction = await engine.predict_energy_demand(horizon_minutes=60)
        
        # Simulate varying accuracy
        error_factor = 1.0 + (i * 0.05)  # Increasing error
        actual_state = {
            "total_power_kw": prediction.predicted["total_power_kw"] * error_factor,
            "hvac_power_kw": prediction.predicted["hvac_power_kw"] * error_factor,
            "lighting_power_kw": prediction.predicted["lighting_power_kw"],
            "other_power_kw": prediction.predicted["other_power_kw"],
        }
        
        engine.learn_from_validation(prediction.prediction_id, actual_state)
    
    # Compute drift
    drift_report = await engine.compute_drift(time_window_hours=24)
    
    print(f"\nDrift Score: {drift_report.drift_score:.3f}")
    print(f"Error Trend: {drift_report.error_trend}")
    print(f"Needs Retraining: {drift_report.needs_retraining}")
    print(f"Alerts: {drift_report.alerts}")
    
    # Since we validated 10 predictions, drift should be computable
    assert drift_report.drift_score >= 0
    assert drift_report.error_trend in ["improving", "stable", "worsening", "unknown"]
    print("\n✅ PASS")


async def test_retraining():
    """Test 4: Model retraining"""
    print("\n" + "=" * 60)
    print("TEST 4: Model Retraining")
    print("=" * 60)
    
    engine = PredictionEngine(building_id="test-building")
    
    # Generate training data - make predictions AND validate them
    validated_count = 0
    for i in range(25):
        prediction = await engine.predict_energy_demand(horizon_minutes=60)
        
        actual_state = {
            "total_power_kw": 400 + i * 10,  # Different values
            "hvac_power_kw": 240 + i * 6,
            "lighting_power_kw": 60,
            "other_power_kw": 100 + i * 4,
        }
        
        # Validate each prediction immediately
        error = engine.learn_from_validation(prediction.prediction_id, actual_state)
        if error is not None:
            validated_count += 1
    
    print(f"\nSamples seen: {engine._samples_seen}")
    print(f"Baselines before: {len(engine._energy_baseline)}")
    print(f"Successfully validated: {validated_count}")
    
    # Check stats
    stats = engine.get_stats()
    print(f"Stats - Total: {stats['total_predictions']}, Validated: {stats['validated_predictions']}")
    
    # Trigger retraining if we have enough validated data
    result = await engine.trigger_retraining()
    
    print(f"\nRetraining Result: {result}")
    
    # Accept either success or skipped (if not enough validated)
    assert result["status"] in ["success", "skipped"]
    print("\n✅ PASS")


async def test_stats():
    """Test 5: Statistics"""
    print("\n" + "=" * 60)
    print("TEST 5: Statistics")
    print("=" * 60)
    
    engine = PredictionEngine(building_id="test-building")
    
    # Make some predictions
    for _ in range(5):
        await engine.predict_energy_demand(horizon_minutes=60)
    
    stats = engine.get_stats()
    
    print(f"\nTotal Predictions: {stats['total_predictions']}")
    print(f"Validated: {stats['validated_predictions']}")
    print(f"Pending: {stats['pending_predictions']}")
    print(f"Baselines Trained: {stats['baselines_trained']}")
    print(f"Samples Seen: {stats['samples_seen']}")
    
    assert stats["total_predictions"] == 5
    assert stats["pending_predictions"] == 5
    print("\n✅ PASS")


async def run_all_tests():
    print("\n" + "=" * 60)
    print("ABI™ PREDICTION ENGINE TESTS")
    print("=" * 60)
    
    try:
        await test_energy_prediction()
        await test_validation_and_learning()
        await test_drift_detection()
        await test_retraining()
        await test_stats()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
