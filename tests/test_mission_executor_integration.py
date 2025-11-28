import unittest
import asyncio
import tempfile
import shutil
from unittest.mock import MagicMock
from agent.event_bus.event_bus import EventBus
from agent_mission.mission_executor import MissionExecutor
from agent_mission.mission_store import MissionStore
from agent_mission.mission_planner import MissionPlanner
from agent_plan.action_router import ActionRouter
from agent_plan.action_executors import (
    SceneExecutor, DeviceExecutor, AutomationExecutor, 
    CollectionExecutor, MonitoringExecutor
)
from agent_plan.scene_engine import SceneEngine
from agent.controllers.matter_controller import MatterController
from agent_mission.base.mission import Mission, MissionStatus
from agent_plan.plan_graph import PlanGraph, PlanNode

class TestMissionExecutorIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.store = MissionStore(storage_path=self.temp_dir)
        self.planner = MagicMock(spec=MissionPlanner)
        
        # Mock underlying engines
        self.scene_engine = MagicMock(spec=SceneEngine)
        self.device_controller = MagicMock(spec=MatterController)
        self.device_controller.turn_on = MagicMock(return_value=True)
        
        # Create real executors
        self.scene_exec = SceneExecutor(self.scene_engine, self.device_controller)
        self.device_exec = DeviceExecutor(self.device_controller)
        self.auto_exec = AutomationExecutor()
        self.coll_exec = CollectionExecutor(self.event_bus)
        self.mon_exec = MonitoringExecutor(self.event_bus)
        
        # Create real router
        self.router = ActionRouter(
            self.scene_exec, self.device_exec, self.auto_exec, 
            self.coll_exec, self.mon_exec
        )
        
        self.executor = MissionExecutor(
            self.event_bus, 
            self.store, 
            self.planner, 
            self.router
        )
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    async def test_end_to_end_mission(self):
        print("\n[Test] End-to-End Mission Execution")
        
        # 1. Setup Mission
        mission = Mission(
            mission_id="integ_mission_001",
            mission_type="energy_saver",
            status=MissionStatus.INIT
        )
        self.store.save_mission(mission)
        
        # 2. Setup Plan (Linear: Scene -> Action)
        plan = PlanGraph()
        
        # Step 1: Apply Scene
        node1 = PlanNode(
            node_id="step1", 
            action="scene", 
            params={"scene_name": "evening_mode"}
        )
        plan.add_node(node1)
        
        # Step 2: Turn on specific light (depends on step1)
        node2 = PlanNode(
            node_id="step2", 
            action="action", 
            params={"device_id": "light_1", "action": "turn_on"},
            depends_on=["step1"]
        )
        plan.add_node(node2)
        
        # 3. Execute
        await self.executor.start_execution("integ_mission_001", plan)
        
        # Wait for completion (poll status)
        for _ in range(20):
            await asyncio.sleep(0.1)
            m = self.store.load_mission("integ_mission_001")
            if m.status in [MissionStatus.COMPLETED, MissionStatus.FAILED]:
                break
                
        # 4. Verify
        final_mission = self.store.load_mission("integ_mission_001")
        if final_mission.status == MissionStatus.FAILED:
            error_msg = f"Mission Failed! History: {final_mission.history}"
            print(error_msg)
            raise RuntimeError(error_msg)
            
        self.assertEqual(final_mission.status, MissionStatus.COMPLETED)
        
        # Verify calls
        self.scene_engine.build_scene_plan.assert_called_with("evening_mode", overrides={"scene_name": "evening_mode"})
        self.device_controller.turn_on.assert_called_with("light_1")
        
        print("✅ Integration test passed")

if __name__ == "__main__":
    unittest.main()