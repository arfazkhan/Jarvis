"""
System-Level Tool Definitions
=============================

Special tools for agent state management and mission boundaries.
"""

from agent_unified.tools.boundary import TaskBoundaryTool

SYSTEM_TOOLS = [
    TaskBoundaryTool().to_param()["function"],
    {
        "name": "replay_investigation",
        "description": "Replay a past investigation from the episodic archive. Lists recent investigations or loads a specific plan by ID. Use to recall what ARVIS previously investigated, what evidence was gathered, and what conclusions were reached.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "Specific investigation plan ID to replay. If omitted, returns list of recent investigations."
                },
                "query_filter": {
                    "type": "string",
                    "description": "Search term to filter investigations by query text (optional)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max investigations to return in list mode (default: 10)",
                    "default": 10
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:investigation_replay"],
        "response_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "description": "list or detail"},
                "investigations": {"type": "array", "description": "List of investigation summaries (list mode)"},
                "plan": {"type": "object", "description": "Full investigation plan with tasks and evidence (detail mode)"}
            }
        }
    },
]

__all__ = ["SYSTEM_TOOLS"]
