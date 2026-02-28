"""
Energy Tool Definitions
=======================

Tools for energy analysis and cost calculations.
"""

ENERGY_TOOLS = [
    {
        "name": "analyze_energy",
        "description": "Analyze energy consumption for a specific period. Detects anomalies, compares to baseline, and identifies waste patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: today, yesterday, this_week, this_month, next_week",
                    "enum": ["today", "yesterday", "this_week", "this_month", "next_week"],
                    "default": "today",
                    "examples": ["today", "this_week"]
                },
                "building_id": {
                    "type": "string",
                    "description": "Optional building filter",
                    "examples": ["main"]
                }
            },
            "required": []
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "total_kwh": {"type": "number"},
                "cost_qar": {"type": "number"},
                "anomalies": {"type": "array"}
            }
        }
    },
    {
        "name": "get_energy_anomalies",
        "description": "Get detected energy waste patterns and anomalies with estimated savings potential.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "check_cost_impact",
        "description": "Calculate the financial cost (QAR) of a proposed temperature change. Shows current burn rate, new burn rate, and daily/monthly impact. Use before any setpoint change to warn users about costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "current_temp": {
                    "type": "number",
                    "description": "Current temperature setpoint in Celsius"
                },
                "target_temp": {
                    "type": "number",
                    "description": "Proposed new temperature setpoint in Celsius"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier (optional)"
                }
            },
            "required": ["current_temp", "target_temp"]
        }
    },
    {
        "name": "get_burn_rate",
        "description": "Get current building energy burn rate in QAR/hour. Shows projected daily and monthly costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier (optional)"
                }
            },
            "required": []
        }
    },
    {
        "name": "find_ghost_spaces",
        "description": "Scan all zones to find 'Ghost Operations' - rooms that are scheduled ON but detected as EMPTY based on CO2 levels. No hardware needed - uses existing BMS sensors. Returns potential savings.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building to scan (optional, defaults to all)"
                }
            },
            "required": []
        }
    },
    {
        "name": "estimate_zone_occupancy",
        "description": "Estimate occupancy for a specific zone using virtual sensing (CO2, VAV position, lighting). Returns probability 0-1 and occupancy level.",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier (e.g., 'ZONE-F1-01')"
                },
                "method": {
                    "type": "string",
                    "description": "Sensing method: co2 (default), vav, lighting, or fusion (all combined)",
                    "enum": ["co2", "vav", "lighting", "fusion"],
                    "default": "fusion"
                }
            },
            "required": ["zone_id"]
        }
    },
]
