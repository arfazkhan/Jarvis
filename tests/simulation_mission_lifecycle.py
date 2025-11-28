import asyncio
import unittest
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any

from agent.event_bus.event_bus import EventBus
from agent_mission.mission_manager import MissionManager
from agent_mission.mission_planner import MissionPlanner
from agent_mission.mission_executor import MissionExecutor
from agent_mission.mission_monitor import MissionMonitor
from agent_mission.mission_store import MissionStore
from agent_mission.user_pattern_store import UserPatternStore
from agent_mission.base.mission import MissionStatus
from agent_mission.base.mission_context import MissionContext

async def main():
    print("\n=== Starting Mission Lifecycle Simulation ===")
    
    # Setup temporary directories
    test_dir = tempfile.mkdtemp()
    try:
        template_dir = Path(test_dir) / "templates"
        template_dir.mkdir()
        store_dir = Path(test_dir) / "store"
        store_dir.mkdir()
        pattern_dir = Path(test_dir) / "patterns"
        pattern_dir.mkdir()
        
        # Create dummy template
        with open(template_dir / "sleep_optimization.yaml", "w") as f:
            f.write("""
mission_id: "sleep_optimization"
description: "Optimize sleep environment"
mission_id: "sleep_optimization"
description: "Optimize sleep environment"
plan_template:
  - step_id: "check_schedule"
    step_type: "collection"
    parameters:
      data_types: ["calendar", "habits"]
  - step_id: "prepare_bedroom"
    step_type: "scene"
    parameters:
      scene_name: "sleep_prep"
      temperature: 20
    dependencies: ["check_schedule"]
  - step_id: "monitor_sleep"
    step_type: "monitoring"
    parameters:
      metrics: ["bedtime_variance", "sleep_duration"]
      continuous: true
    dependencies: ["prepare_bedroom"]
""")

        # Initialize components
        event_bus = EventBus()
        
        # Initialize stores with temp paths
        mission_store = MissionStore(storage_path=str(store_dir))
        pattern_store = UserPatternStore(storage_path=str(pattern_dir))
        
        # Initialize Manager and inject store
        manager = MissionManager(event_bus, template_dir=str(template_dir))
        manager.store = mission_store
        
        # Initialize other components
        planner = MissionPlanner(template_dir=str(template_dir))
        executor = MissionExecutor(event_bus, mission_store, planner)
        monitor = MissionMonitor(event_bus, mission_store)
        
        # 1. Start Mission
        context = MissionContext(user_id="test_user")
        mission = manager.start_mission("sleep_optimization", context)
        print(f"Mission started: {mission.status}")
        
        # 2. Wait for Execution
        print("Waiting for execution...")
        await asyncio.sleep(2.0)
        
        # Reload mission
        mission = manager.store.load_mission(mission.mission_id)
        print(f"Mission Status after execution: {mission.status}")
        
        # 3. Simulate Monitoring Update
        print("Simulating monitoring update...")
        mock_metrics = {
            "bedtime_variance": 50.0,
            "sleep_duration": 6.0
        }
        mission.metrics.update(mock_metrics)
        manager.store.save_mission(mission)
        
        # Prepare mock sensor data
        mock_sensor_data = {
            "bedtimes": [23.5, 23.0, 24.5], # High variance
            "wake_times": [7.0, 7.1, 7.0],
            "night_motion_count": 15
        }
        
        # Evaluate
        evaluation = monitor.evaluate_mission(mission.mission_id, mock_sensor_data)
        print(f"Evaluation result: {evaluation}")
        
        # 4. Adaptation
        if evaluation["needs_adaptation"]:
            print("Adaptation required. Rebuilding plan...")
            new_plan = planner.rebuild_plan(
                old_plan=None,
                metrics=evaluation["metrics"],
                mission_type=mission.mission_type,
                context=mission.context
            )
            print(f"New context: {mission.context}")
            await executor.execute_mission(mission.mission_id, new_plan)
            
        # 5. Stop Mission
        print("Stopping mission...")
        manager.stop_mission(mission.mission_id)
        
        print("=== Simulation Complete ===")
        
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(main())
