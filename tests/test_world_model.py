
import pytest
from datetime import datetime, timedelta
from agent_advisory.world_model import WorldModel, StateTransitionModel, WorldState

def test_transition_model_heuristics():
    """Test that heuristics update the state as expected"""
    model = StateTransitionModel()
    
    initial_state = WorldState(
        timestamp=datetime.now(),
        features={
            "power_consumption_kw": 100.0,
            "zone_temp_avg": 23.0,
            "efficiency_kw_rt": 1.0
        },
        raw_context={}
    )
    
    # Test Reduce Load
    next_s = model.predict_next_state(initial_state, "reduce_load")
    assert next_s.features["power_consumption_kw"] == 90.0 # 0.9 * 100
    assert next_s.features["zone_temp_avg"] == 23.2 # 23 + 0.2
    assert next_s.timestamp > initial_state.timestamp
    
    # Test Stage Down
    next_s = model.predict_next_state(initial_state, "stage_down")
    assert next_s.features["power_consumption_kw"] == 75.0 # 0.75 * 100
    assert next_s.features["zone_temp_avg"] == 23.5 # 23 + 0.5

def test_simulation_trajectory():
    """Test multi-step simulation"""
    tm = StateTransitionModel()
    wm = WorldModel(tm)
    
    initial_context = {
        "timestamp": datetime.now().isoformat(),
        "power_consumption_kw": 100.0,
        "zone_temp_avg": 23.0,
        "hour_sin": 0,
        "hour_cos": 1
    }
    
    horizon = 4
    traj = wm.simulate_action(initial_context, "reduce_load", horizon=horizon)
    
    assert len(traj.predicted_states) == horizon
    assert len(traj.predicted_rewards) == horizon
    assert len(traj.actions) == horizon
    assert traj.actions[0] == "reduce_load"
    assert traj.actions[1] == "no_op"
    
    # Check drift (heuristic)
    # Step 1: Power 90 (reduce_load)
    # Step 2: Power 90 (no_op) -> assuming no_op keeps state or drift?
    # Our heuristic for no_op wasn't explicitly defined, so it falls through to environmental drift
    # Check implementation: if action not matched, features copied + drift
    
    print(f"Trajectory Rewards: {traj.predicted_rewards}")
    assert traj.total_reward < 0 # Cost is negative
    
if __name__ == "__main__":
    test_transition_model_heuristics()
    test_simulation_trajectory()
    print("✅ World Model Tests Passed")
