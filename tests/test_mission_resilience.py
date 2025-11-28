import unittest
import asyncio
import shutil
import time
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_mission.mission_executor import MissionExecutor, MissionRuntimeState
from agent_mission.mission_store import MissionStore
from agent_mission.base.mission import Mission, MissionStatus
from agent_mission.base.mission_step import MissionStep, StepType, StepStatus
from agent.event_bus.event_bus import EventBus
from agent_plan.plan_graph import PlanGraph, PlanNode

class TestMissionResilience(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/data/missions_resilience"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        self.bus = EventBus()
        self.store = MissionStore(storage_path=self.test_dir)
        self.planner = MagicMock()
        self.router = MagicMock()
        self.router.execute = MagicMock(return_value={"status": "done"})
        
        self.executor = MissionExecutor(self.bus, self.store, self.planner, self.router)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_pause_resume(self):
        """Test pausing and resuming a mission."""
        mission_id = "mission_pause_test"
        mission = Mission(
            mission_id=mission_id, 
            mission_type="energy_saver",
            status=MissionStatus.EXECUTING
        )
        self.store.save_mission(mission)
        
        # Manually inject state
        state = MissionRuntimeState(mission_id=mission_id)
        self.executor.active_states[mission_id] = state
        
        # Pause
        self.executor.pause_mission(mission_id)
        self.assertTrue(state.paused)
        
        # Check persistence
        loaded_mission = self.store.load_mission(mission_id)
        self.assertTrue(loaded_mission.runtime_state["paused"])
        
        # Resume
        self.executor.resume_mission(mission_id)
        self.assertFalse(state.paused)
        
        loaded_mission = self.store.load_mission(mission_id)
        self.assertFalse(loaded_mission.runtime_state["paused"])

    def test_retry_logic(self):
        """Test that steps are retried on failure."""
        async def run_test():
            mission_id = "mission_retry_test"
            mission = Mission(
                mission_id=mission_id, 
                mission_type="energy_saver",
                status=MissionStatus.EXECUTING
            )
            self.store.save_mission(mission)
            
            # Setup context
            context = MagicMock()
            context.metadata = {"mission_id": mission_id}
            
            # Setup step with retries
            step = MissionStep(
                step_id="step_1",
                step_type=StepType.ACTION,
                parameters={},
                retry_count=2
            )
            
            state = MissionRuntimeState(mission_id=mission_id)
            
            # Mock router to fail twice then succeed
            self.router.execute.side_effect = [
                Exception("Fail 1"),
                Exception("Fail 2"),
                {"status": "success"}
            ]
            
            success, error = await self.executor._execute_single_step(step, context, state)
            
            self.assertTrue(success)
            self.assertIsNone(error)
            self.assertEqual(self.router.execute.call_count, 3)
            self.assertEqual(state.step_status["step_1"], StepStatus.SUCCESS.value)
            
        asyncio.run(run_test())

    def test_recovery(self):
        """Test recovering an interrupted mission."""
        async def run_test():
            mission_id = "mission_recovery_test"
            mission = Mission(
                mission_id=mission_id, 
                mission_type="energy_saver",
                status=MissionStatus.EXECUTING
            )
            
            # Create a fake runtime state
            state = MissionRuntimeState(mission_id=mission_id, current_layer_index=1)
            mission.runtime_state = state.to_dict()
            
            # Save to store (simulate crash while executing)
            self.store.save_mission(mission)
            
            # Ensure not in memory
            self.executor.active_states.clear()
            
            # Mock resume_execution to verify it's called
            self.executor.resume_execution = AsyncMock()
            
            # Run recovery
            await self.executor.recover_active_missions()
            
            self.executor.resume_execution.assert_called_with(mission_id)
            
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
