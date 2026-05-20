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
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:maintenance_prediction"],
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
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:remaining_useful_life"],
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
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:maintenance_verification"],
        "response_schema": {
            "type": "object",
            "properties": {
                "work_order_id": {"type": "string"},
                "equipment_id": {"type": "string"},
                "verified": {"type": "boolean", "description": "True if telemetry confirms maintenance was performed"},
                "verdict": {"type": "string", "description": "CONFIRMED, GHOST_MAINTENANCE, or INSUFFICIENT_DATA"},
                "pre_metric": {"type": "number", "description": "Metric value before maintenance"},
                "post_metric": {"type": "number", "description": "Metric value after maintenance"},
                "improvement_pct": {"type": "number"},
                "evidence_summary": {"type": "string"}
            }
        }
    },
    {
        "name": "predict_filter_degradation",
        "description": "Predict when AHU filters will need replacement based on differential pressure trend analysis. Uses rolling DP data to extrapolate time-to-threshold and generate early warnings weeks before failure. Returns projected replacement date, confidence, and recommendation.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "AHU equipment identifier (optional — returns all tracked filters if omitted)",
                    "examples": ["AHU-01"]
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:filter_degradation"],
        "response_schema": {
            "type": "object",
            "properties": {
                "filters": {"type": "array"},
                "summary": {"type": "string"}
            }
        }
    },
]
