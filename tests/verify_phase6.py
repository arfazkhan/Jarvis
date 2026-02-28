import asyncio
import logging
import json
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from agent_commercial.bms_llm_agent import BMSLLMAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_phase6")

async def verify_phase6():
    print("🚀 Starting Phase 6: Online Learning & Trust Calibration Verification...")
    
    # 1. Initialize Agent (This now includes Phase 6 components)
    agent = BMSLLMAgent()
    
    print("\n--- Testing Online Learning (Drift Detection) ---")
    # Simulate some initial observations to establish baseline
    for i in range(50):
        # State: {'total_power_kw': 400 + noise}
        pred = {"total_power_kw": 400}
        actual = {"total_power_kw": 400 + (i % 5)}
        agent.online_learner.log_observation(pred, actual)
        
    print(f"Baseline RMSE Established: {agent.online_learner.baseline_rmse:.3f}")
    
    # Now simulate Drift (e.g., sensor malfunction or building behavior change)
    print("Simulating sensor drift (Error increase)...")
    for i in range(20):
        pred = {"total_power_kw": 400}
        actual = {"total_power_kw": 550 + (i % 10)} # 150kW error!
        agent.online_learner.log_observation(pred, actual)
        
    perf = agent.online_learner.get_performance_summary()
    print(f"Current Drift Ratio: {perf.get('drift_ratio', 0):.2f}")
    if perf.get('drift_ratio', 0) > 1.5:
        print("✅ Online Learning detected drift and would trigger retraining.")
    
    print("\n--- Testing Trust Calibration ---")
    # Mock some recommendations and outcomes in the tracker
    from agent_advisory.schemas import Recommendation, RecommendationStatus
    import uuid
    
    print("Mucking recommendations...")
    # Recommendation 1: Accepted and Successful
    rec1 = Recommendation(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        context={},
        trigger_type="test",
        recommended_action={"action": "test_action_1"},
        confidence=0.9,
    )
    rec1.status = RecommendationStatus.ACCEPTED
    rec1.actual_outcome = {"utility_score": 0.85}
    
    print("Injecting Rec 1...")
    # Manually inject into advisor tracker (mocking for test)
    # Correct signature: context, recommended_action, confidence, reasoning, predicted_outcome, ...
    agent.advisor.tracker.log_recommendation(
        context={}, 
        recommended_action=rec1.recommended_action, 
        confidence=rec1.confidence, 
        reasoning="test",
        predicted_outcome=None
    )
    # The log_recommendation call above generates a NEW ID. 
    # For the test, we actually want to test the update logic, so we should use the ID it returns.
    row = agent.advisor.tracker.db.fetch_one("SELECT id FROM recommendations ORDER BY timestamp DESC LIMIT 1")
    test_rec_id = row["id"]
    
    # Update statuses
    agent.advisor.tracker.db.execute("UPDATE recommendations SET status = ?, actual_outcome = ? WHERE id = ?", 
                                     (rec1.status.value, json.dumps(rec1.actual_outcome), test_rec_id))
    
    print("Calculating metrics...")
    trust_metrics = agent.trust_calibrator.calculate_trust_metrics()
    print(f"Overall Trust Score: {trust_metrics.get('overall_trust_score', 0):.2f}")
    
    print("\n--- Testing Tool Exposure ---")
    result = await agent.tool_handler.execute("get_trust_metrics", {"window_days": 7})
    print(f"Tool Result Status: {result.get('system_status')}")
    print(f"Adoption Rate: {result.get('trust_metrics', {}).get('adoption_rate', 0):.0%}")
    
    print("\n✅ Phase 6 Verification COMPLETE.")

import json
if __name__ == "__main__":
    asyncio.run(verify_phase6())
