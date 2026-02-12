
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from agent_advisory.explainer import ExplanationEngine, DetailLevel
from agent_advisory.world_model import WorldModel, StateTransitionModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_explainer")

async def verify_explainer():
    print("🚀 Starting Explanation Engine Verification...")
    
    # 1. Setup World Model (Heuristic mode)
    tm = StateTransitionModel()
    wm = WorldModel(tm)
    
    # 2. Setup Explainer
    explainer = ExplanationEngine(world_model=wm)
    
    # 3. Define a recommendation
    recommendation = {
        "title": "Reduce AHU-02 Load",
        "description": "Lowering cooling output on AHU-02 to prevent high head pressure on Chiller-01.",
        "action_type": "reduce_load",
        "priority": "High",
        "potential_savings_qar": 120.0
    }
    
    # 4. Define context
    context = {
        "total_power_kw": 450.0,
        "zone_temp_avg_c": 24.2,
        "outdoor_temp_c": 45.0
    }
    
    # 5. Test BRIEF level
    print("\n--- Testing BRIEF Explanation ---")
    brief = await explainer.explain_recommendation(recommendation, context, level=DetailLevel.BRIEF)
    print(f"Text: {brief['text']}")
    
    # 6. Test STANDARD level
    print("\n--- Testing STANDARD Explanation ---")
    standard = await explainer.explain_recommendation(recommendation, context, level=DetailLevel.STANDARD)
    print(f"Text: {standard['text']}")
    print(f"Causal Chain: {' -> '.join(standard['causal_chain'])}")
    
    # 7. Test DETAILED level
    print("\n--- Testing DETAILED Explanation ---")
    detailed = await explainer.explain_recommendation(recommendation, context, level=DetailLevel.DETAILED)
    print(f"Text: {detailed['text']}")
    print(f"Counterfactual: {detailed['counterfactual']}")
    
    print("\n✅ Verification COMPLETE: Explanation Engine successfully generated multi-level insights.")

if __name__ == "__main__":
    asyncio.run(verify_explainer())
