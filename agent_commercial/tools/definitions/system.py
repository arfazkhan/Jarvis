"""
System-Level Tool Definitions
=============================

Special tools for agent state management and mission boundaries.
"""

from agent_unified.tools.boundary import TaskBoundaryTool

SYSTEM_TOOLS = [
    TaskBoundaryTool().to_param()["function"],
]

__all__ = ["SYSTEM_TOOLS"]
