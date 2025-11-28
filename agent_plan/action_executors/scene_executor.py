"""
Scene Executor
--------------
Executes SCENE steps by interacting with the SceneEngine.
"""

from typing import Dict, Any
from agent_mission.base.mission_step import MissionStep
from agent_mission.base.mission_context import MissionContext
from agent_plan.scene_engine import SceneEngine
from agent.controllers.matter_controller import MatterController

class SceneExecutor:
    def __init__(self, scene_engine: SceneEngine, device_controller: MatterController):
        self.scene_engine = scene_engine
        self.device_controller = device_controller
        
    def execute(self, step: MissionStep, context: MissionContext) -> Dict[str, Any]:
        """
        Execute a SCENE step.
        """
        params = step.parameters
        scene_name = params.get("scene_name")
        if not scene_name:
            raise ValueError("SCENE step requires 'scene_name' parameter")
            
        # 1. Resolve scene into steps
        plan_steps = self.scene_engine.build_scene_plan(scene_name, overrides=params)
        
        # 2. Execute each step
        results = {}
        for plan_step in plan_steps:
            device_id = plan_step["params"]["device"]
            action = plan_step["action"]
            
            # Simple mapping for MVP
            if action in ["set_light", "turn_on"]:
                self.device_controller.turn_on(device_id)
                results[device_id] = "on"
            elif action == "turn_off":
                self.device_controller.turn_off(device_id)
                results[device_id] = "off"
            # Add more actions as needed
            
        return {"status": "success", "executed_steps": len(plan_steps), "details": results}
