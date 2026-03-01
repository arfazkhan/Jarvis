"""
BMS Tools Module
================

Modular tool definitions and handlers for ARVIS Ops Copilot.
Split from the monolithic tools_schema.py for maintainability.

Structure:
- definitions/: Tool schema definitions by category
- handlers/: Tool execution handlers
- prompts/: System prompts for Ops Copilot

Usage:
    from agent_commercial.tools import BMS_TOOLS, BMSToolHandler
    
    # Get tool definitions for LLM
    tools = BMS_TOOLS
    
    # Execute tools
    handler = BMSToolHandler(bms_state=bms, alarm_engine=alarms)
    result = await handler.execute("get_equipment_status", {"equipment_id": "AHU-01"})
"""

# Tool definitions - lazy import to avoid circular dependencies
def get_bms_tools():
    """Get all BMS tool definitions."""
    from agent_commercial.tools.definitions import BMS_TOOLS
    return BMS_TOOLS


# Expose tool categories at module level (loaded on first access)
_tools_loaded = False
_tools_cache = {}

def _ensure_tools_loaded():
    """Lazily load tool definitions."""
    global _tools_loaded, _tools_cache
    if not _tools_loaded:
        from agent_commercial.tools.definitions import (
            BMS_TOOLS,
            EQUIPMENT_TOOLS,
            ALARM_TOOLS,
            ENERGY_TOOLS,
            MAINTENANCE_TOOLS,
            GSAS_TOOLS,
            ADVISORY_TOOLS,
            ML_TOOLS,
            SOVEREIGN_TOOLS,
            get_all_tools,
        )
        _tools_cache = {
            "BMS_TOOLS": BMS_TOOLS,
            "EQUIPMENT_TOOLS": EQUIPMENT_TOOLS,
            "ALARM_TOOLS": ALARM_TOOLS,
            "ENERGY_TOOLS": ENERGY_TOOLS,
            "MAINTENANCE_TOOLS": MAINTENANCE_TOOLS,
            "GSAS_TOOLS": GSAS_TOOLS,
            "ADVISORY_TOOLS": ADVISORY_TOOLS,
            "ML_TOOLS": ML_TOOLS,
            "SOVEREIGN_TOOLS": SOVEREIGN_TOOLS,
            "get_all_tools": get_all_tools,
        }
        _tools_loaded = True
    return _tools_cache

# Module-level accessors for backward compatibility
def __getattr__(name):
    """Lazy load tool definitions on first access."""
    tools = _ensure_tools_loaded()
    if name in tools:
        return tools[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Handlers - import directly
from agent_commercial.tools.handlers import (
    BMSToolHandler,
    BMSToolHandlerSync,
)

# Prompts - import directly
from agent_commercial.tools.prompts import (
    OPS_COPILOT_SYSTEM_PROMPT,
    OPS_COPILOT_SYSTEM_PROMPT_ARABIC,
    OPS_COPILOT_SYSTEM_PROMPT_AR,
    get_ops_copilot_prompt,
)

__all__ = [
    # Tool definitions
    "BMS_TOOLS",
    "EQUIPMENT_TOOLS",
    "ALARM_TOOLS",
    "ENERGY_TOOLS",
    "MAINTENANCE_TOOLS",
    "GSAS_TOOLS",
    "ADVISORY_TOOLS",
    "ML_TOOLS",
    "SOVEREIGN_TOOLS",
    "get_all_tools",
    # Handlers
    "BMSToolHandler",
    "BMSToolHandlerSync",
    # Prompts
    "OPS_COPILOT_SYSTEM_PROMPT",
    "OPS_COPILOT_SYSTEM_PROMPT_ARABIC",
    "OPS_COPILOT_SYSTEM_PROMPT_AR",
    "get_ops_copilot_prompt",
]
