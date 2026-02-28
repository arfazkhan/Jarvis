"""
ML-Powered Tool Definitions
===========================

Tools that leverage machine learning for advanced analytics.
"""

ML_TOOLS = [
    {
        "name": "forecast_energy",
        "description": "Forecast future energy demand using ML ensemble (Prophet + LightGBM). Provides hourly predictions with confidence intervals, considers Qatar-specific features like Ramadan, sandstorms, and extreme heat. Also detects anomalies in consumption patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "forecast_hours": {
                    "type": "integer",
                    "description": "Hours to forecast (default: 24, max: 168)",
                    "default": 24,
                    "examples": [24, 168]
                },
                "building_id": {
                    "type": "string",
                    "description": "Building to forecast (optional)",
                    "examples": ["tower_a"]
                },
                "include_confidence": {
                    "type": "boolean",
                    "description": "Include confidence intervals (default: true)",
                    "default": True
                }
            },
            "required": []
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "forecast": {"type": "array"},
                "peak_demand": {"type": "number"},
                "confidence_bounds": {"type": "object"}
            }
        }
    },
    {
        "name": "detect_equipment_faults",
        "description": "Use ML autoencoder to detect equipment faults from sensor data. Applies physics-constrained VAE and ASHRAE RP-1312 fault rules. Returns fault type, severity, confidence, and recommended action.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Equipment to analyze",
                    "examples": ["AHU-01"]
                },
                "fault_type": {
                    "type": "string",
                    "description": "Specific fault to check (optional): sensor_drift, valve_stuck, refrigerant_leak, heat_exchanger_fouling",
                    "enum": ["sensor_drift", "valve_stuck", "refrigerant_leak", "heat_exchanger_fouling"],
                    "examples": ["sensor_drift"]
                }
            },
            "required": ["equipment_id"]
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "faults": {"type": "array"},
                "health_score": {"type": "number"}
            }
        }
    },
    {
        "name": "analyze_root_cause",
        "description": "Use Bayesian Network causal inference to find root cause of alarm cascades. Considers equipment topology, temporal sequence, and physical causality. Returns probability-weighted root causes and cascade prediction.",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of related alarm IDs"
                },
                "system_depth": {
                    "type": "integer",
                    "description": "How deep to analyze the system graph (default: 3)",
                    "default": 3
                }
            },
            "required": ["alarm_ids"]
        }
    },
    {
        "name": "simulate_with_uncertainty",
        "description": "Advanced what-if simulation using Gaussian Process regression and Monte Carlo. Provides uncertainty bounds & risk assessment for operational changes. Shows worst-case scenario and probability of negative outcomes.",
        "parameters": {
            "type": "object",
            "properties": {
                "change_type": {
                    "type": "string",
                    "description": "Type of change: setpoint, schedule, equipment_speed",
                    "enum": ["setpoint", "schedule", "equipment_speed"]
                },
                "current_value": {
                    "type": "number",
                    "description": "Current value"
                },
                "proposed_value": {
                    "type": "number",
                    "description": "Proposed new value"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Affected equipment (optional)"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Affected zone (optional)"
                },
                "monte_carlo_samples": {
                    "type": "integer",
                    "description": "Number of Monte Carlo samples (default: 1000)",
                    "default": 1000
                }
            },
            "required": ["change_type", "current_value", "proposed_value"]
        }
    },
    {
        "name": "find_similar_skills",
        "description": "Use semantic embeddings to find relevant building skills from the Skillbook. Matches based on meaning not just keywords. Returns ranked list of applicable skills with similarity scores.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query (e.g., 'chiller not cooling efficiently')"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default: 5)",
                    "default": 5
                },
                "equipment_type": {
                    "type": "string",
                    "description": "Filter by equipment type (optional)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "benchmark_building_ml",
        "description": "Use ML clustering to identify building archetype and benchmark against similar buildings. Returns percentile rankings, archetype classification (e.g., 'Large Office Cooling-Dominated'), and improvement recommendations from similar high performers.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building to benchmark (optional, uses default)"
                },
                "comparison_scope": {
                    "type": "string",
                    "description": "Scope: local_fleet, regional, global",
                    "enum": ["local_fleet", "regional", "global"],
                    "default": "local_fleet"
                }
            },
            "required": []
        }
    },
]
