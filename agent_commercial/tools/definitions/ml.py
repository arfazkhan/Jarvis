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
        "version": "1.0.0",
        "cost_class": "expensive",
        "precedents": [],
        "produces": ["evidence:energy_forecast"],
        "response_schema": {
            "type": "object",
            "properties": {
                "forecast": {"type": "array"},
                "peak_demand": {"type": "number"},
                "confidence_bounds": {"type": "object"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
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
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:equipment_faults"],
        "response_schema": {
            "type": "object",
            "properties": {
                "faults": {"type": "array"},
                "health_score": {"type": "number"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
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
        },
        "version": "1.0.0",
        "cost_class": "expensive",
        "precedents": ["get_active_alarms"],
        "produces": ["evidence:root_cause_analysis"],
        "response_schema": {
            "type": "object",
            "properties": {
                "root_causes": {"type": "array", "description": "Probability-weighted root cause candidates each with equipment_id, probability, and causal_path"},
                "top_root_cause": {"type": "string", "description": "Most probable root cause equipment"},
                "confidence": {"type": "number"},
                "cascade_prediction": {"type": "array", "description": "Alarms predicted to fire next if root cause is not addressed"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
            }
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
        },
        "version": "1.0.0",
        "cost_class": "expensive",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:uncertainty_simulation"],
        "response_schema": {
            "type": "object",
            "properties": {
                "expected_outcome": {"type": "number", "description": "Mean predicted result value"},
                "confidence_interval_low": {"type": "number"},
                "confidence_interval_high": {"type": "number"},
                "probability_negative_outcome": {"type": "number", "description": "0-1 probability of an adverse result"},
                "worst_case": {"type": "number"},
                "energy_delta_kwh": {"type": "number"},
                "risk_assessment": {"type": "string"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
            }
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
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:similar_skills"],
        "response_schema": {
            "type": "object",
            "properties": {
                "skills": {"type": "array", "description": "Matched skillbook entries each with skill_id, title, skill_type, similarity_score, and description"},
                "total_matches": {"type": "integer"},
                "query_embedding_used": {"type": "boolean"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
            }
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
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:ml_benchmark"],
        "response_schema": {
            "type": "object",
            "properties": {
                "archetype": {"type": "string", "description": "Building archetype classification (e.g., 'Large Office Cooling-Dominated')"},
                "percentile_rank": {"type": "number", "description": "Percentile among archetype peers (0-100)"},
                "eui_kwh_m2": {"type": "number", "description": "Energy Use Intensity in kWh/m²/year"},
                "peer_average_eui": {"type": "number"},
                "improvement_recommendations": {"type": "array", "description": "Best practices from top-performing peers"},
                "comparison_scope": {"type": "string"},
                "_ml_lineage": {"type": "object", "description": "ML provenance metadata (model_id, version, drift_score)"}
            }
        }
    },
]
