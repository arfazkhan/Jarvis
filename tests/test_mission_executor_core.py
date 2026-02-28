import unittest
import asyncio
import tempfile
import shutil
from unittest.mock import MagicMock, AsyncMock
from arvis_core.event_bus.event_bus import EventBus
from agent_mission.mission_executor import MissionExecutor, MissionRuntimeState
from agent_mission.mission_store import MissionStore
from agent_mission.mission_planner import MissionPlanner
from agent_plan.action_router import ActionRouter
from agent_mission.base.mission import Mission, MissionStatus
from agent_plan.plan_graph import PlanGraph, PlanNode

class TestMissionExecutorCore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.store = MissionStore(storage_path=self.temp_dir)
        self.planner = MagicMock(spec=MissionPlanner)
        
        # Mock ActionRouter
        self.action_router = MagicMock(spec=ActionRouter)
        self.action_router.execute.return_value = {"status": "success"}
        
        self.executor = MissionExecutor(
            self.event_bus, 
            self.store, 
            self.planner, 
            self.action_router
        )
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    async def test_start_execution(self):
        print("\n[Test] Start Execution")
        
        # Create a dummy mission
        mission = Mission(
            mission_id="test_mission_001",
            mission_type="energy_saver",
            status=MissionStatus.INIT
        )
        self.store.save_mission(mission)
        
        # Create a dummy plan
        plan = PlanGraph()
        node1 = PlanNode(node_id="step1", action="action", params={"device_id": "light1", "action": "turn_on"})
        plan.add_node(node1)
        
        # Start execution
        await self.executor.start_execution("test_mission_001", plan)
        
        # Verify state initialized
        self.assertIn("test_mission_001", self.executor.active_states)
        state = self.executor.active_states["test_mission_001"]
        self.assertEqual(state.mission_id, "test_mission_001")
        self.assertEqual(state.step_status["step1"], "pending")
        
        # Verify mission updated in store
        updated_mission = self.store.load_mission("test_mission_001")
        self.assertEqual(updated_mission.status, MissionStatus.EXECUTING)
        self.assertIsNotNone(updated_mission.runtime_state)
        
        # Wait a bit for async loop (it runs in background)
        await asyncio.sleep(0.1)
        
    async def test_cancel_mission(self):
        print("\n[Test] Cancel Mission")
        
        # Setup active state
        state = MissionRuntimeState(mission_id="test_mission_002")
        self.executor.active_states["test_mission_002"] = state
        
        # Cancel
        self.executor.cancel_mission("test_mission_002")
        
        self.assertTrue(state.cancelled)
        
    async def test_persistence(self):
        print("\n[Test] Persistence")
        
        # Create mission
        mission = Mission(
            mission_id="test_mission_003",
            mission_type="energy_saver",
            status=MissionStatus.EXECUTING
        )
        self.store.save_mission(mission)
        
        # Manually inject state
        state = MissionRuntimeState(mission_id="test_mission_003", current_layer_index=2)
        self.executor.active_states["test_mission_003"] = state
        
        # Trigger persist
        self.executor._persist_state("test_mission_003")
        
        # Check store
        loaded = self.store.load_mission("test_mission_003")
        self.assertEqual(loaded.runtime_state["current_layer_index"], 2)

if __name__ == "__main__":
    unittest.main()
