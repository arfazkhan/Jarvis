"""
BMS Tool Definitions
====================

Modular tool schema definitions organized by category.
Each category contains related tool definitions for the LLM.
"""

from agent_commercial.tools.definitions.equipment import EQUIPMENT_TOOLS
from agent_commercial.tools.definitions.alarms import ALARM_TOOLS
from agent_commercial.tools.definitions.energy import ENERGY_TOOLS
from agent_commercial.tools.definitions.maintenance import MAINTENANCE_TOOLS
from agent_commercial.tools.definitions.gsas import GSAS_TOOLS
from agent_commercial.tools.definitions.advisory import ADVISORY_TOOLS
from agent_commercial.tools.definitions.ml import ML_TOOLS
from agent_commercial.tools.definitions.sovereign import SOVEREIGN_TOOLS
from agent_commercial.tools.definitions.system import SYSTEM_TOOLS


def get_all_tools() -> list:
    """Get all BMS tool definitions combined."""
    return (
        EQUIPMENT_TOOLS +
        ALARM_TOOLS +
        ENERGY_TOOLS +
        MAINTENANCE_TOOLS +
        GSAS_TOOLS +
        ADVISORY_TOOLS +
        ML_TOOLS +
        SOVEREIGN_TOOLS +
        SYSTEM_TOOLS
    )


# Combined list for backward compatibility
BMS_TOOLS = get_all_tools()

__all__ = [
    "BMS_TOOLS",
    "EQUIPMENT_TOOLS",
    "ALARM_TOOLS",
    "ENERGY_TOOLS",
    "MAINTENANCE_TOOLS",
    "GSAS_TOOLS",
    "ADVISORY_TOOLS",
    "ML_TOOLS",
    "SOVEREIGN_TOOLS",
    "SYSTEM_TOOLS",
    "get_all_tools",
]
