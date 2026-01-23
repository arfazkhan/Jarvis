"""
Terminate Tool
==============

Special tool to signal agent completion.
"""

from .base import BaseTool, ToolResult


class Terminate(BaseTool):
    """
    Tool to terminate agent execution.
    
    When called, signals the agent to finish its current run.
    """
    
    name: str = "terminate"
    description: str = "Terminate the current task and signal completion. Use this when the task is fully completed or cannot be continued."
    parameters: dict = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Final status message explaining the outcome",
                "enum": ["success", "failure", "cancelled"]
            },
            "message": {
                "type": "string",
                "description": "Summary of what was accomplished or why terminating"
            }
        },
        "required": ["status"]
    }
    
    async def execute(self, status: str = "success", message: str = "") -> ToolResult:
        """
        Execute termination.
        
        Args:
            status: Termination status (success/failure/cancelled)
            message: Summary message
            
        Returns:
            ToolResult with termination info
        """
        result = {
            "terminated": True,
            "status": status,
            "message": message or f"Task {status}"
        }
        return self.success_response(result)
