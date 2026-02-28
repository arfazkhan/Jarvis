"""
Maintenance Tool Definitions
=============================

Tools for predictive maintenance and equipment lifecycle management.
"""

MAINTENANCE_TOOLS = [
    {
        "name": "predict_maintenance",
        "description": "Get predictive maintenance analysis for equipment, including failure probability, remaining useful life, and recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Specific equipment to analyze (optional, returns all if not specified)",
                    "examples": ["AHU-01"]
                },
                "risk_level": {
                    "type": "string",
                    "description": "Filter by risk level: low, medium, high, critical",
                    "enum": ["low", "medium", "high", "critical"],
                    "examples": ["high"]
                }
            },
            "required": []
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "insights": {"type": "array"}
            }
        }
    },
    {
        "name": "predict_remaining_life",
        "description": "Predict the Remaining Useful Life (RUL) for equipment. Returns health score, days until predicted failure, probability of failure at various timeframes, and degradation indicators. Use this to answer 'Will the chiller make it through summer?'",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Equipment identifier",
                    "examples": ["CH-01"]
                },
                "forecast_days": {
                    "type": "integer",
                    "description": "How many days ahead to forecast (default: 90)",
                    "default": 90,
                    "examples": [30]
                }
            },
            "required": ["equipment_id"]
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "health_score": {"type": "number"},
                "days_to_failure": {"type": "integer"}
            }
        }
    },
    {
        "name": "verify_maintenance_work",
        "description": "Verify if maintenance work was actually done by comparing pre/post telemetry using physics. Catches 'Ghost Maintenance' where work is marked complete but no improvement measured.",
        "parameters": {
            "type": "object",
            "properties": {
                "work_order_id": {
                    "type": "string",
                    "description": "Work order identifier"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Equipment that was serviced"
                },
                "expected_improvement": {
                    "type": "string",
                    "description": "What should have improved: efficiency, capacity, noise, vibration, temperature",
                    "enum": ["efficiency", "capacity", "noise", "vibration", "temperature"]
                }
            },
            "required": ["work_order_id", "equipment_id"]
        }
    },
]
