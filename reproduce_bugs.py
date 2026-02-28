import sys
import os

# Ensure we can import modules from current directory
sys.path.append(os.getcwd())

try:
    print("Testing find_ghost_spaces...")
    from agent_commercial.virtual_sensors import find_ghost_spaces
    result = find_ghost_spaces()
    print("find_ghost_spaces: OK")
except Exception as e:
    print(f"find_ghost_spaces FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("-" * 20)

try:
    print("Testing simulate_change...")
    from agent_commercial.simulator import simulate_change
    result = simulate_change(change_type="setpoint", current_value=22, proposed_value=23)
    print("simulate_change: OK")
except Exception as e:
    print(f"simulate_change FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
