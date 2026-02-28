"""
BMS Tools Schema - Backward Compatibility Shim
==============================================

This module provides backward compatibility for code that imports from
the old monolithic tools_schema.py file.

New code should import from agent_commercial.tools instead:
    from agent_commercial.tools import BMS_TOOLS, BMSToolHandler

This shim will be deprecated in a future version.
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "Importing from 'agent_commercial.tools_schema' is deprecated. "
    "Use 'from agent_commercial.tools import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the new modular structure
from agent_commercial.tools import (
    # Tool definitions
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
    # Handlers
    BMSToolHandler,
    BMSToolHandlerSync,
    # Prompts
    OPS_COPILOT_SYSTEM_PROMPT,
    OPS_COPILOT_SYSTEM_PROMPT_ARABIC,
    OPS_COPILOT_SYSTEM_PROMPT_AR,
    get_ops_copilot_prompt,
)

# Additional backward compatibility functions
def get_bms_tools():
    """Get the list of BMS tool definitions. Deprecated: use BMS_TOOLS directly."""
    return BMS_TOOLS


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
    "get_bms_tools",
    # Handlers
    "BMSToolHandler",
    "BMSToolHandlerSync",
    # Prompts
    "OPS_COPILOT_SYSTEM_PROMPT",
    "OPS_COPILOT_SYSTEM_PROMPT_ARABIC",
    "OPS_COPILOT_SYSTEM_PROMPT_AR",
    "get_ops_copilot_prompt",
]
