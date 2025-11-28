import unittest
from unittest.mock import MagicMock
from agent_mission.base.mission_step import MissionStep, StepType
from agent_mission.base.mission_context import MissionContext
from agent_plan.action_router import ActionRouter
from agent_plan.action_executors import (
    SceneExecutor, DeviceExecutor, AutomationExecutor, 
    CollectionExecutor, MonitoringExecutor
)

class TestActionRouterAndExecutors(unittest.TestCase):
    def setUp(self):
        self.scene_exec = MagicMock(spec=SceneExecutor)
        self.device_exec = MagicMock(spec=DeviceExecutor)
        self.auto_exec = MagicMock(spec=AutomationExecutor)
        self.coll_exec = MagicMock(spec=CollectionExecutor)
        self.mon_exec = MagicMock(spec=MonitoringExecutor)
        
        self.router = ActionRouter(
            self.scene_exec, self.device_exec, self.auto_exec, 
            self.coll_exec, self.mon_exec
        )
        
        self.context = MissionContext(user_id="user")
        self.context.metadata["mission_id"] = "test"
        
    def test_route_scene(self):
        step = MissionStep(step_id="s1", step_type=StepType.SCENE, parameters={"scene_name": "bedtime"})
        self.router.execute(step, self.context)
        self.scene_exec.execute.assert_called_once_with(step, self.context)
        
    def test_route_action(self):
        step = MissionStep(step_id="s2", step_type=StepType.ACTION, parameters={"device_id": "d1", "action": "on"})
        self.router.execute(step, self.context)
        self.device_exec.execute.assert_called_once_with(step, self.context)
        
    def test_route_automation(self):
        step = MissionStep(step_id="s3", step_type=StepType.AUTOMATION, parameters={"routine_name": "r1"})
        self.router.execute(step, self.context)
        self.auto_exec.execute.assert_called_once_with(step, self.context)
        
    def test_route_collection(self):
        step = MissionStep(step_id="s4", step_type=StepType.COLLECTION, parameters={"data_type": "sleep"})
        self.router.execute(step, self.context)
        self.coll_exec.execute.assert_called_once_with(step, self.context)
        
    def test_route_monitoring(self):
        step = MissionStep(step_id="s5", step_type=StepType.MONITORING, parameters={"metric": "temp"})
        self.router.execute(step, self.context)
        self.mon_exec.execute.assert_called_once_with(step, self.context)

if __name__ == "__main__":
    unittest.main()
