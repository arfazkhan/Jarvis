"""
Device Executor
---------------
Executes ACTION steps by interacting with the DeviceController (MatterController).
"""

from typing import Dict, Any
from agent_mission.base.mission_step import MissionStep
from agent_mission.base.mission_context import MissionContext
from agent_home.controllers.matter_controller import MatterController

class DeviceExecutor:
    def __init__(self, device_controller: MatterController):
        self.device_controller = device_controller

    def execute(self, step: MissionStep, context: MissionContext) -> Dict[str, Any]:
        """
        Execute an ACTION step (Device Control).
        
        Parameters:
            step: The mission step containing action parameters.
            context: The execution context.
            
        Returns:
            Dict containing execution results.
        """
        params = step.parameters
        device_id = params.get("device_id")
        action = params.get("action")
        
        if not device_id or not action:
            raise ValueError("ACTION step requires 'device_id' and 'action' parameters")
            
        # Execute via MatterController
        # Note: MatterController methods are dynamic (turn_on, set_level, etc.)
        # We use getattr to find the method
        
        if not hasattr(self.device_controller, action):
             raise ValueError(f"DeviceController has no action '{action}'")
             
        method = getattr(self.device_controller, action)
        
        # Filter params to pass only what's needed (excluding device_id/action)
        action_args = {k: v for k, v in params.items() if k not in ["device_id", "action"]}
        
        # Most controller methods take device_id as first arg
        # e.g. turn_on(device_id, endpoint=1)
        result = method(device_id, **action_args)
        
        return {
            "status": "success",
            "device_id": device_id,
            "action": action,
            "result": result
        }
