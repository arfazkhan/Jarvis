from typing import Any, Dict, Optional
from datetime import datetime
from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.schema import TaskBoundary

class TaskBoundaryTool(BaseTool):
    """
    Standard tool for defining and updating task boundaries.
    Mirrors the Antigravity task_boundary tool for ARVIS.
    """
    name: str = "task_boundary"
    description: str = (
        "Indicate the start of a task or update the current task. "
        "Use this as your VERY FIRST tool call when starting a new objective. "
        "Arguments: task_name, mode (PLANNING/EXECUTION/VERIFICATION), summary, status, predicted_task_size."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "task_name": {"type": "string"},
            "mode": {"type": "string", "enum": ["PLANNING", "EXECUTION", "VERIFICATION"]},
            "summary": {"type": "string"},
            "status": {"type": "string"},
            "predicted_task_size": {"type": "integer"}
        },
        "required": ["task_name", "mode", "summary", "status", "predicted_task_size"]
    }

    async def execute(self, **kwargs) -> ToolResult:
        # Note: The actual state update is handled in the Agent.act() loop 
        # since it needs access to the agent's memory/state. 
        # This implementation just returns the metadata for confirmation.
        try:
            boundary = TaskBoundary(
                task_name=kwargs.get("task_name"),
                mode=kwargs.get("mode", "EXECUTION"),
                summary=kwargs.get("summary"),
                status=kwargs.get("status"),
                predicted_size=kwargs.get("predicted_task_size", 1)
            )
            return self.success_response(boundary.model_dump())
        except Exception as e:
            return self.fail_response(str(e))
