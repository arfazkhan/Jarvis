"""
Monitoring Executor
-------------------
Executes MONITORING steps (Continuous observation).
"""

from typing import Dict, Any
from agent_mission.base.mission_step import MissionStep
from agent_mission.base.mission_context import MissionContext

class MonitoringExecutor:
    def __init__(self, event_bus):
        self.event_bus = event_bus

    def execute(self, step: MissionStep, context: MissionContext) -> Dict[str, Any]:
        """
        Execute a MONITORING step.
        
        Parameters:
            step: The mission step containing monitoring parameters.
            context: The execution context.
            
        Returns:
            Dict containing execution results.
        """
        params = step.parameters
        metric = params.get("metric")
        target = params.get("target")
        
        # Monitoring steps are unique: they don't "finish" instantly usually.
        # However, in the PlanGraph, a step usually blocks dependents.
        # If this is a "Start Monitoring" step, it succeeds immediately.
        # If it's a "Wait for Condition" step, it should block (async).
        
        # For this architecture, we assume "Start Monitoring" semantics.
        # The MissionMonitor is responsible for checking if the condition is met later.
        
        print(f"[MonitoringExecutor] Started monitoring {metric} target {target}")
        
        return {
            "status": "success",
            "monitor_id": f"mon_{metric}_{context.mission_id}",
            "active": True
        }
