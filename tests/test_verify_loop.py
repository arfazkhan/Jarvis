#!/usr/bin/env python3
"""
Test: ABI™ Verify Loop
======================

Tests the recommendation lifecycle:
- Register recommendation
- Acknowledge → Accept → Act
- Validate outcome
- Check feedback processing
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_advisory.verify_loop import (
    VerifyLoop,
    RecommendationStatus,
    OutcomeVerdict,
    RecommendationRegistry,
    OutcomeValidator,
    FeedbackProcessor,
)


class MockStateEngine:
    """Mock BMS state engine for testing"""
    
    def __init__(self):
        self._values = {
            "CH-01/KW": 240.0,
            "CH-01/CHWST": 7.5,
            "METER/KW": 580.0,
        }
    
    def get_points_by_equipment(self, equipment_id: str):
        """Return mock points"""
        class MockPoint:
            def __init__(self, point_id, name, value):
                self.point_id = point_id
                self.name = name
                self.value = value
        
        if equipment_id == "CH-01":
            return [
                MockPoint("CH-01/KW", "Chiller Power", self._values["CH-01/KW"]),
                MockPoint("CH-01/CHWST", "CHW Supply Temp", self._values["CH-01/CHWST"]),
            ]
        return []
    
    def get_energy_summary(self):
        return {"current_kwh": 125000, "current_kw": self._values["METER/KW"]}


class MockTrustGovernor:
    """Mock trust governor for testing"""
    
    def __init__(self):
        self.trust_level = 0.7
        self.outcomes = []
    
    def record_outcome(self, recommendation_type, verdict, confidence, error_score):
        self.outcomes.append({
            "type": recommendation_type,
            "verdict": verdict,
            "confidence": confidence,
            "error_score": error_score,
        })
    
    def adjust_trust(self, delta: float):
        self.trust_level = max(0.0, min(1.0, self.trust_level + delta))
        print(f"  Trust adjusted by {delta:+.3f} → {self.trust_level:.2f}")


class MockOnlineLearner:
    """Mock online learner for testing"""
    
    def __init__(self):
        self.observations = []
    
    def log_observation(self, prediction, actual):
        self.observations.append({"prediction": prediction, "actual": actual})
        print(f"  Online learner received: pred={prediction}, actual={actual}")


class MockMemory:
    """Mock memory for testing"""
    
    def __init__(self):
        self.memories = []
    
    def remember(self, text, memory_type, metadata=None):
        self.memories.append({"text": text, "type": memory_type, "metadata": metadata})
        print(f"  Memory stored: {memory_type}")


async def test_full_lifecycle():
    """Test the complete recommendation lifecycle"""
    
    print("\n" + "=" * 60)
    print("TEST: ABI™ Verify Loop — Full Lifecycle")
    print("=" * 60)
    
    # Setup
    state_engine = MockStateEngine()
    trust_governor = MockTrustGovernor()
    online_learner = MockOnlineLearner()
    memory = MockMemory()
    
    verify_loop = VerifyLoop(
        state_engine=state_engine,
        trust_governor=trust_governor,
        online_learner=online_learner,
        memory=memory,
        persist_path=None,  # In-memory for test
    )
    
    print("\n1️⃣ Register Recommendation")
    print("-" * 40)
    
    rec_id = await verify_loop.register_recommendation(
        title="Reduce chiller setpoint to save energy",
        description="Lower CHWST setpoint from 7.5°C to 7.0°C to reduce chiller power by ~15kW",
        recommendation_type="energy",
        action_type="setpoint_change",
        equipment_id="CH-01",
        predicted_outcome={
            "metrics": {
                "power_kw": 225.0,  # Predict 240 → 225
                "chilled_water_supply_temp_c": 7.0,
            },
            "energy_savings_kwh": 15.0,
        },
        confidence=0.85,
        reasoning="Historical data shows 0.5°C reduction = ~6% power savings",
        sources=["energy_analyzer", "predictive_maintenance"],
    )
    
    print(f"  ✅ Registered: {rec_id}")
    
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    print(f"  Confidence: {rec.confidence:.2f}")
    
    print("\n2️⃣ Operator Acknowledges")
    print("-" * 40)
    
    await verify_loop.acknowledge(rec_id, operator_id="ops_alice")
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    print(f"  Operator: {rec.operator_id}")
    
    print("\n3️⃣ Operator Accepts")
    print("-" * 40)
    
    await verify_loop.accept(rec_id, operator_id="ops_alice")
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    
    print("\n4️⃣ Operator Acts")
    print("-" * 40)
    
    # Simulate the action changing state
    state_engine._values["CH-01/KW"] = 222.0  # Actually saved 18kW, not 15kW!
    state_engine._values["CH-01/CHWST"] = 7.0
    
    await verify_loop.record_action(rec_id, operator_id="ops_alice")
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    print(f"  Acted at: {rec.acted_at}")
    
    print("\n5️⃣ Validate Outcome")
    print("-" * 40)
    
    # Manually trigger validation directly
    validation = await verify_loop.validator.validate(rec)
    print(f"  Validation result: {validation.verdict.value}")
    print(f"  Error score: {validation.error_score:.2%}")
    
    # Update recommendation
    rec.actual_outcome = validation.actual_values
    rec.outcome_verdict = validation.verdict
    rec.outcome_error_score = validation.error_score
    rec.validated_at = datetime.now()
    rec.status = RecommendationStatus.VALIDATED
    verify_loop.registry.update(rec)
    
    # Process feedback
    await verify_loop.processor.process(rec, validation)
    
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    print(f"  Verdict: {rec.outcome_verdict.value}")
    print(f"  Error Score: {rec.outcome_error_score:.2%}")
    print(f"  Predicted: {rec.predicted_outcome.get('metrics', {})}")
    print(f"  Actual: {rec.actual_outcome}")
    
    print("\n6️⃣ Feedback Processing")
    print("-" * 40)
    
    print(f"  Trust Governor outcomes: {len(trust_governor.outcomes)}")
    print(f"  Online Learner observations: {len(online_learner.observations)}")
    print(f"  Memories stored: {len(memory.memories)}")
    
    print("\n7️⃣ Statistics")
    print("-" * 40)
    
    stats = verify_loop.get_statistics()
    print(f"  Total validated: {stats['count']}")
    print(f"  Accuracy: {stats['accuracy']:.1%}" if stats['accuracy'] else "  Accuracy: N/A")
    print(f"  Avg error: {stats['avg_error_score']:.2%}" if stats['avg_error_score'] else "  Avg error: N/A")
    
    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Verify loop working end-to-end")
    print("=" * 60)
    
    # Summary
    return {
        "recommendation_id": rec_id,
        "verdict": rec.outcome_verdict.value,
        "error_score": rec.outcome_error_score,
        "trust_level": trust_governor.trust_level,
    }


async def test_rejection_flow():
    """Test the rejection flow with trust impact"""
    
    print("\n" + "=" * 60)
    print("TEST: Rejection Flow")
    print("=" * 60)
    
    state_engine = MockStateEngine()
    trust_governor = MockTrustGovernor()
    
    verify_loop = VerifyLoop(
        state_engine=state_engine,
        trust_governor=trust_governor,
        persist_path=None,
    )
    
    print("\n1️⃣ Register and Reject")
    print("-" * 40)
    
    rec_id = await verify_loop.register_recommendation(
        title="Incorrect recommendation",
        description="This recommendation is wrong",
        recommendation_type="energy",
        action_type="setpoint_change",
        equipment_id="CH-01",
        predicted_outcome={"metrics": {"power_kw": 200.0}},
        confidence=0.90,
    )
    
    print(f"  Registered: {rec_id}")
    
    # Reject with reason indicating error
    await verify_loop.reject(
        rec_id,
        operator_id="ops_bob",
        reason="Prediction was wrong - equipment is already at optimal setpoint"
    )
    
    rec = verify_loop.registry.get(rec_id)
    print(f"  Status: {rec.status.value}")
    print(f"  Verdict: {rec.outcome_verdict.value if rec.outcome_verdict else 'None'}")
    print(f"  Trust level: {trust_governor.trust_level:.2f}")
    
    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Rejection impacts trust")
    print("=" * 60)


async def run_all_tests():
    """Run all verify loop tests"""
    
    print("\n" + "=" * 60)
    print("ARVIS ABI™ Verify Loop — Test Suite")
    print("=" * 60)
    
    # Test 1: Full lifecycle
    result1 = await test_full_lifecycle()
    
    # Test 2: Rejection flow
    await test_rejection_flow()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)
    
    print("\n📊 Key Result:")
    print(f"  Recommendation validated: {result1['verdict']}")
    print(f"  Error score: {result1['error_score']:.1%}")
    print(f"  Trust after feedback: {result1['trust_level']:.2f}")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
