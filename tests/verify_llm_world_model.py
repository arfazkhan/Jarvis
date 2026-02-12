
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from agent_advisory.qatar.llm_simulator import LLMEnhancedSimulator
from agent_advisory.world_model import WorldModel, StateTransitionModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_world_model")

async def verify_pipeline():
    print("🚀 Starting LLM-Enhanced World Model Verification...")
    
    # 1. Initialize Simulator (LLM-Powered)
    simulator = LLMEnhancedSimulator(seed=42)
    
    # 2. Generate small but realistic dataset
    print("--- Step 1: Generating LLM-Enhanced Synthetic Data ---")
    # Generating 5 scenarios to keep it fast for verification
    scenarios = await simulator.generate_diverse_dataset(n=5)
    
    for s in scenarios:
        print(f"Scenario: {s.issue_type} | Narrative: {s.context.get('narrative', 'N/A')}")
        
    # 3. Train World Model
    print("\n--- Step 2: Training World Model Transition Models ---")
    tm = StateTransitionModel()
    # Increase to 200 scenarios for better ML accuracy
    base_scenarios = simulator.generate_scenarios(n=200)
    all_scenarios = base_scenarios + scenarios
    
    tm.train([s.to_dict() for s in all_scenarios])
    
    # 4. Run Simulation
    print("\n--- Step 3: Running Predictive Simulation (Rollout) ---")
    wm = WorldModel(tm)
    
    # Pick a high-heat context
    initial_context = {
        "timestamp": datetime.now().isoformat(),
        "outdoor_temp_c": 45.0,
        "total_power_kw": 500.0,
        "zone_temp_avg_c": 24.5,
        "cooling_load_pct": 90.0
    }
    
    # Simulate "reduce_load" action for 1 hour (4 steps)
    trajectory = wm.simulate_action(initial_context, "reduce_load", horizon=4)
    
    print(f"Initial Power: {initial_context['total_power_kw']} kW")
    print(f"Initial Temp: {initial_context['zone_temp_avg_c']} C")
    
    for i, state in enumerate(trajectory.predicted_states):
        power = state.features.get("total_power_kw", 0)
        temp = state.features.get("zone_temp_avg_c", 22)
        reward = trajectory.predicted_rewards[i]
        print(f"Step {i+1}: Power={power:.1f} kW, Temp={temp:.1f} C, Step Utility={reward:.2f}")
        
    print(f"\nTotal Trajectory Utility: {trajectory.total_reward:.2f}")
    
    # 5. Assertions
    assert len(trajectory.predicted_states) == 4
    assert tm.is_trained == True
    # In 'reduce_load', power should generally be lower than initial or trending down
    assert trajectory.predicted_states[0].features["total_power_kw"] < 500.0
    
    print("\n✅ Verification SUCCESS: World Model learned from LLM-enhanced data and predicted plausible trajectories.")

if __name__ == "__main__":
    asyncio.run(verify_pipeline())
