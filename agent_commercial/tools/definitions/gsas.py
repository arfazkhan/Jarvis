"""
GSAS Tool Definitions
=====================

Tools for GSAS (Global Sustainability Assessment System) compliance and reporting.
"""

GSAS_TOOLS = [
    {
        "name": "get_gsas_status",
        "description": "Get current GSAS (Global Sustainability Assessment System) compliance status including scores by category and recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "The building identifier (optional, defaults to 'main')",
                    "examples": ["tower_a"]
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:gsas_status"],
        "response_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "rating": {"type": "string"},
                "categories": {"type": "object"}
            }
        }
    },
    {
        "name": "get_gsas_improvement_priorities",
        "description": "Get prioritized list of GSAS improvements ranked by impact on overall score. Shows the top 10 actions to take to improve the building's GSAS rating.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gsas_improvement_priorities"],
        "response_schema": {
            "type": "object",
            "properties": {
                "priorities": {"type": "array", "description": "Ordered list of improvement actions with category, score_delta, effort, and description"},
                "current_score": {"type": "number"},
                "achievable_score": {"type": "number", "description": "Score if all listed priorities are addressed"}
            }
        }
    },
    {
        "name": "optimize_recommendations_for_gsas",
        "description": "Score and rank operational recommendations by their contribution to GSAS targets. Use this before surfacing recommendations when compliance impact matters.",
        "parameters": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "description": "Recommendations to score. Each item can include title, description, goal_type, source_engine, priority, potential_savings_qar, equipment_ids, and suggested_actions.",
                    "items": {"type": "object"}
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of optimized recommendations to return",
                    "default": 10
                }
            },
            "required": ["recommendations"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gsas_optimized_recommendations"],
        "response_schema": {
            "type": "object",
            "properties": {
                "optimized_recommendations": {"type": "array", "description": "Recommendations re-ranked with gsas_score_delta and compliance_category appended"},
                "total_scored": {"type": "integer"},
                "top_gsas_category": {"type": "string", "description": "GSAS category with highest combined improvement opportunity"}
            }
        }
    },
    {
        "name": "generate_gord_report",
        "description": "Generate a GORD-compliant PDF report for GSAS Operations certification. This is the official report format required for submission to GORD (Gulf Organisation for Research & Development) for certification renewal. The report includes building scores, category breakdowns, BMS evidence, and signature blocks.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier (optional, uses default if not provided)"
                },
                "building_name": {
                    "type": "string",
                    "description": "Building display name (optional)"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "expensive",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gord_report"],
        "response_schema": {
            "type": "object",
            "properties": {
                "report_path": {"type": "string", "description": "File path to the generated PDF report"},
                "report_id": {"type": "string"},
                "gsas_score": {"type": "number"},
                "gsas_rating": {"type": "string"},
                "generated_at": {"type": "string"},
                "page_count": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_zone_occupancy",
        "description": "Returns occupancy patterns and confidence for a specific zone based on BMS signals (CO2, lighting, access control).",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Identifier of the zone (e.g., 'floor_7_zone_a')"
                }
            },
            "required": ["zone_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:zone_occupancy"],
        "response_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string"},
                "is_occupied": {"type": "boolean"},
                "occupancy_probability": {"type": "number"},
                "occupancy_pattern": {"type": "object", "description": "Hourly occupancy profile for the zone"},
                "signals_used": {"type": "array", "description": "BMS signals that contributed to the estimate"},
                "confidence": {"type": "number"}
            }
        }
    },
    {
        "name": "predict_comfort_impact",
        "description": "Predicts the thermal comfort impact and risk of a proposed BMS action on a zone and its adjacent zones.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "description": "The proposed BMS action, e.g., {'type': 'setpoint_optimization', 'params': {'setpoint': 25.0}}"
                },
                "zone_id": {
                    "type": "string",
                    "description": "The target zone identifier"
                }
            },
            "required": ["action", "zone_id"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:comfort_impact"],
        "response_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string"},
                "predicted_pmv": {"type": "number", "description": "Predicted Mean Vote comfort index (-3 to +3)"},
                "comfort_risk": {"type": "string", "description": "none, low, medium, or high"},
                "adjacent_zones_affected": {"type": "array", "description": "Zones that may experience secondary comfort impact"},
                "recommendation": {"type": "string"}
            }
        }
    },
    {
        "name": "get_financial_projection",
        "description": "Projects the financial savings (in QAR) and payback period for a proposed BMS action based on energy/water reductions.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "description": "The proposed BMS action"
                },
                "energy_delta_kwh": {
                    "type": "number",
                    "description": "Estimated energy reduction in kWh per month"
                },
                "water_delta_m3": {
                    "type": "number",
                    "description": "Estimated water reduction in cubic meters per month (optional)",
                    "default": 0.0
                }
            },
            "required": ["action", "energy_delta_kwh"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:financial_projection"],
        "response_schema": {
            "type": "object",
            "properties": {
                "monthly_savings_qar": {"type": "number"},
                "annual_savings_qar": {"type": "number"},
                "energy_savings_kwh_month": {"type": "number"},
                "water_savings_m3_month": {"type": "number"},
                "payback_months": {"type": "number", "description": "Months to recoup any implementation cost"},
                "co2_reduction_kg_month": {"type": "number"}
            }
        }
    },
    {
        "name": "get_gsas_contextual_recommendations",
        "description": "Runs the GSAS Optimizer and returns raw contextual recommendations including occupancy context, comfort prediction, and financial projection. Used to synthesize reasoning chains.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recommendations to return",
                    "default": 5
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gsas_contextual_recommendations"],
        "response_schema": {
            "type": "object",
            "properties": {
                "recommendations": {"type": "array", "description": "Contextual recommendations each containing action, occupancy_context, comfort_prediction, financial_projection, and gsas_score_delta"},
                "optimizer_run_id": {"type": "string"},
                "generated_at": {"type": "string"}
            }
        }
    },
    {
        "name": "simulate_gsas_impact",
        "description": "Simulates the impact of a proposed BMS action on the GSAS score. Projects the score delta before execution. Should be called to verify if a recommendation is safe to implement.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "description": "The proposed BMS action"
                }
            },
            "required": ["action"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:gsas_impact_simulation"],
        "response_schema": {
            "type": "object",
            "properties": {
                "current_gsas_score": {"type": "number"},
                "projected_gsas_score": {"type": "number"},
                "score_delta": {"type": "number", "description": "Positive means improvement"},
                "affected_categories": {"type": "object", "description": "Per-category score deltas"},
                "safe_to_implement": {"type": "boolean"},
                "warnings": {"type": "array"}
            }
        }
    },
    {
        "name": "classify_gsas_action_risk",
        "description": "Returns the governance tier (AUTO_EXECUTE, NOTIFY_AND_EXECUTE, REQUIRE_APPROVAL) for a proposed action based on its risk and simulated GSAS impact. Call this to determine if an action needs human-in-the-loop approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "description": "The proposed BMS action"
                },
                "simulation_result": {
                    "type": "object",
                    "description": "The result from simulate_gsas_impact"
                }
            },
            "required": ["action", "simulation_result"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["simulate_gsas_impact"],
        "produces": ["evidence:gsas_action_risk"],
        "response_schema": {
            "type": "object",
            "properties": {
                "governance_tier": {"type": "string", "description": "AUTO_EXECUTE, NOTIFY_AND_EXECUTE, or REQUIRE_APPROVAL"},
                "risk_level": {"type": "string", "description": "low, medium, high, or critical"},
                "rationale": {"type": "string", "description": "Explanation for the tier assignment"},
                "requires_human_approval": {"type": "boolean"}
            }
        }
    },
    {
        "name": "record_gsas_action_outcome",
        "description": "Record the facility manager's decision on a proposed GSAS action. Use this to remember if the FM approved, rejected, or modified a recommendation.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "description": "The proposed BMS action"
                },
                "decision": {
                    "type": "string",
                    "enum": ["APPROVED", "REJECTED", "MODIFIED"],
                    "description": "The FM's decision"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes from the FM explaining their decision"
                }
            },
            "required": ["action", "decision"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["classify_gsas_action_risk"],
        "produces": ["evidence:gsas_action_outcome"],
        "response_schema": {
            "type": "object",
            "properties": {
                "recorded": {"type": "boolean"},
                "outcome_id": {"type": "string"},
                "decision": {"type": "string"},
                "action_type": {"type": "string"},
                "timestamp": {"type": "string"}
            }
        }
    },
    {
        "name": "get_gsas_success_rates",
        "description": "Get the historical approval rate for GSAS actions. Use this to determine if the FM typically rejects certain types of recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "Optional action type to filter by (e.g., 'setpoint_adjustment')"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:gsas_success_rates"],
        "response_schema": {
            "type": "object",
            "properties": {
                "overall_approval_rate": {"type": "number", "description": "0-1 fraction of actions approved by FM"},
                "by_action_type": {"type": "object", "description": "Per action-type approval rates"},
                "total_recorded": {"type": "integer"},
                "most_rejected_type": {"type": "string"}
            }
        }
    },
    {
        "name": "check_gsas_audit_readiness",
        "description": "Evaluates whether the building could pass a GSAS audit right now. Returns readiness score and blocking issues.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gsas_audit_readiness"],
        "response_schema": {
            "type": "object",
            "properties": {
                "readiness_score": {"type": "number", "description": "0-100 audit readiness score"},
                "audit_ready": {"type": "boolean"},
                "blocking_issues": {"type": "array", "description": "Issues that would cause an audit failure"},
                "warning_issues": {"type": "array", "description": "Issues that would reduce score but not block certification"},
                "estimated_gsas_score": {"type": "number"}
            }
        }
    },
    {
        "name": "detect_gsas_score_drift",
        "description": "Detects if the GSAS score is drifting downwards over a window of time. Returns drift direction, magnitude, and alert level.",
        "parameters": {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": "Number of days to check for drift (defaults to 30)"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_gsas_status"],
        "produces": ["evidence:gsas_score_drift"],
        "response_schema": {
            "type": "object",
            "properties": {
                "drift_detected": {"type": "boolean"},
                "drift_direction": {"type": "string", "description": "improving, stable, or degrading"},
                "drift_magnitude": {"type": "number", "description": "Score change over the window"},
                "alert_level": {"type": "string", "description": "none, warning, or critical"},
                "start_score": {"type": "number"},
                "current_score": {"type": "number"},
                "window_days": {"type": "integer"}
            }
        }
    }
]
