"""
Action Router
-------------
Routes MissionSteps to the appropriate specialized executor based on step type.
"""

from typing import Dict, Any
from agent_mission.base.mission_step import MissionStep, StepType
from agent_mission.base.mission_context import MissionContext

from agent_plan.action_executors.scene_executor import SceneExecutor
from agent_plan.action_executors.device_executor import DeviceExecutor
from agent_plan.action_executors.automation_executor import AutomationExecutor
from agent_plan.action_executors.collection_executor import CollectionExecutor
from agent_plan.action_executors.monitoring_executor import MonitoringExecutor

class ActionRouter:
    def __init__(self, 
                 scene_executor: SceneExecutor,
                 device_executor: DeviceExecutor,
                 automation_executor: AutomationExecutor,
                 collection_executor: CollectionExecutor,
                 monitoring_executor: MonitoringExecutor):
        self.scene_executor = scene_executor
        self.device_executor = device_executor
        self.automation_executor = automation_executor
        self.collection_executor = collection_executor
        self.monitoring_executor = monitoring_executor

    def execute(self, step: MissionStep, context: MissionContext) -> Dict[str, Any]:
        """
        Route the step to the correct executor.
        
        Parameters:
            step: The mission step to execute.
            context: The execution context.
            
        Returns:
            Dict containing execution results.
        """
        step_type = step.step_type
        
        # Handle string or enum
        if hasattr(step_type, "value"):
            step_type = step_type.value
        
        if step_type == "scene":
            return self.scene_executor.execute(step, context)
        elif step_type == "action":
            return self.device_executor.execute(step, context)
        elif step_type == "automation":
            return self.automation_executor.execute(step, context)
        elif step_type == "collection":
            return self.collection_executor.execute(step, context)
        elif step_type == "monitoring":
            return self.monitoring_executor.execute(step, context)
        else:
            raise ValueError(f"Unknown step type: {step_type}")
