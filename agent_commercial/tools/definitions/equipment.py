"""
Equipment Tool Definitions
==========================

Tools for querying and managing BMS equipment.
"""

EQUIPMENT_TOOLS = [
    {
        "name": "get_equipment_status",
        "description": "Get the current status of a specific piece of BMS equipment including its operational state, data points, and active alarms.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment identifier (e.g., 'AHU-01', 'CH-01')",
                    "examples": ["AHU-01", "CH-02", "PUMP-01"]
                }
            },
            "required": ["equipment_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:equipment_status"],
        "response_schema": {
            "type": "object",
            "properties": {
                "equipment": {"type": "object", "description": "Core equipment metadata"},
                "data_points": {"type": "array", "description": "Current values for all sensor/control points"}
            }
        }
    },
    {
        "name": "list_equipment",
        "description": "List all BMS equipment, optionally filtered by type, status, or location.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_type": {
                    "type": "string",
                    "description": "Filter by type: air_handling_unit, chiller, vav, fcu, pump, etc.",
                    "enum": ["air_handling_unit", "chiller", "vav", "fcu", "pump", "boiler", "cooling_tower"],
                    "examples": ["air_handling_unit", "chiller"]
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: running, stopped, fault, maintenance",
                    "enum": ["running", "stopped", "fault", "maintenance", "offline"],
                    "examples": ["fault", "running"]
                },
                "location": {
                    "type": "string",
                    "description": "Filter by location (building, floor, zone)",
                    "examples": ["Floor 1", "Zone-B"]
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for results (default: 1)",
                    "default": 1
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:equipment_list"],
        "response_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "equipment": {"type": "array"},
                "total_pages": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_equipment_health",
        "description": "Get detailed health analysis for specific equipment including health score, trending, and risk factors.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment identifier"
                }
            },
            "required": ["equipment_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:equipment_health"],
        "response_schema": {
            "type": "object",
            "properties": {
                "equipment_id": {"type": "string"},
                "health_score": {"type": "number", "description": "0-100 health score"},
                "trend": {"type": "string", "description": "improving, stable, or degrading"},
                "risk_factors": {"type": "array", "description": "List of identified risk factors"},
                "recommended_actions": {"type": "array", "description": "Suggested maintenance or operational actions"}
            }
        }
    },
    {
        "name": "get_point_history",
        "description": "Get historical values for a specific data point over a time period.",
        "parameters": {
            "type": "object",
            "properties": {
                "point_id": {
                    "type": "string",
                    "description": "The data point identifier (e.g., 'AHU-01/SAT')"
                },
                "minutes": {
                    "type": "integer",
                    "description": "How many minutes of history to retrieve (default: 60, max: 1440)",
                    "default": 60
                }
            },
            "required": ["point_id"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:point_history"],
        "response_schema": {
            "type": "object",
            "properties": {
                "point_id": {"type": "string"},
                "unit": {"type": "string", "description": "Engineering unit (e.g., °C, %, kW)"},
                "readings": {"type": "array", "description": "List of {timestamp, value} pairs"},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "avg": {"type": "number"}
            }
        }
    },
    {
        "name": "get_equipment_specs",
        "description": "Search local technical manuals and specifications for a specific equipment or system. Use this to find hardware limits, manufacturer setpoints, or maintenance requirements.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Equipment identifier (e.g., 'AHU-01', 'CH-01')"
                },
                "query": {
                    "type": "string",
                    "description": "Specific information to search for (e.g., 'capacity', 'setpoints', 'maintenance schedule')"
                }
            },
            "required": ["equipment_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:equipment_specs"],
        "response_schema": {
            "type": "object",
            "properties": {
                "equipment_id": {"type": "string"},
                "manufacturer": {"type": "string"},
                "model": {"type": "string"},
                "specs": {"type": "object", "description": "Key-value map of specification fields"},
                "matched_sections": {"type": "array", "description": "Relevant manual excerpts matching the query"},
                "source_document": {"type": "string", "description": "Source manual or datasheet filename"}
            }
        }
    },
    {
        "name": "hybrid_search_knowledge",
        "description": "Search technical manuals using hybrid RAG. Automatically routes to tree search for document structure/procedures, vector search for exact semantic facts, or both for specs/tables/performance data.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The technical question or document search query"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Optional equipment identifier to filter results"
                },
                "strategy": {
                    "type": "string",
                    "enum": ["auto", "tree", "vector", "hybrid"],
                    "description": "Retrieval path. Use auto unless debugging.",
                    "default": "auto"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 5
                }
            },
            "required": ["query"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:knowledge_search"],
        "response_schema": {
            "type": "object",
            "properties": {
                "results": {"type": "array", "description": "Ranked list of matching knowledge chunks"},
                "strategy_used": {"type": "string", "description": "Actual retrieval strategy applied (tree/vector/hybrid)"},
                "total_matches": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_dashboard_overview",
        "description": "Get a summary overview of the building's current status including equipment counts, active alarms, energy metrics, and pending insights.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:dashboard_overview"],
        "response_schema": {
            "type": "object",
            "properties": {
                "equipment_summary": {"type": "object", "description": "Counts by status: running, stopped, fault, maintenance"},
                "active_alarm_count": {"type": "integer"},
                "critical_alarm_count": {"type": "integer"},
                "energy_today_kwh": {"type": "number"},
                "energy_cost_today_qar": {"type": "number"},
                "gsas_score": {"type": "number"},
                "pending_insights": {"type": "array", "description": "Unacknowledged proactive recommendations"},
                "timestamp": {"type": "string"}
            }
        }
    },
    {
        "name": "get_point_inventory",
        "description": (
            "Returns the BACnet point inventory ARVIS can see, with optional filters. "
            "Use this when the operator asks what points are mapped, what's missing, "
            "what's stale, or claims to see a point in Desigo that ARVIS doesn't report. "
            "Returns: total_points, mapped_points, unmapped_points, stale_points, "
            "by_equipment (per-device point list with status), blind_spots (points known "
            "in BACnet but not polled by ARVIS)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_filter": {
                    "type": "string",
                    "description": "Optional. Filter by equipment id substring, e.g. 'CH-02' or 'AHU'."
                },
                "point_filter": {
                    "type": "string",
                    "description": "Optional. Filter by point name substring, e.g. 'FLT_DP' or 'TEMP'."
                },
                "include_stale": {
                    "type": "boolean",
                    "description": "Include points with age > 300s. Default true.",
                    "default": True
                },
                "include_unmapped": {
                    "type": "boolean",
                    "description": "Include points present in BACnet but not polled by ARVIS. Default true.",
                    "default": True
                },
                "summary_only": {
                    "type": "boolean",
                    "description": "If true, omit per-point detail and return only counts + blind_spots. Default false.",
                    "default": False
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:point_inventory"],
        "response_schema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Active provider: sim or production"},
                "total_points": {"type": "integer"},
                "mapped_points": {"type": "integer", "description": "Points polled by ARVIS"},
                "unmapped_points": {"type": "integer", "description": "Points in BACnet but not polled"},
                "stale_points": {"type": "integer", "description": "Points whose last update is older than 300s"},
                "by_equipment": {"type": "object", "description": "Per-device point map with status and missing critical points"},
                "blind_spots": {"type": "object", "description": "Critical points missing across equipment"}
            }
        }
    },
    {
        "name": "get_calibration_status",
        "description": "Query the statistics-based point and equipment calibrations from the database. Shows the count of active calibrations, breakdowns by scope level, and details for promoted thresholds.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Optional equipment identifier to filter calibrations (e.g. 'AHU-19')"
                },
                "point_id": {
                    "type": "string",
                    "description": "Optional point identifier to filter calibrations (e.g. 'AHU-19/DMPR_POS')"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:calibration_status"],
        "response_schema": {
            "type": "object",
            "properties": {
                "active_calibrations": {"type": "integer", "description": "Count of promoted calibrations in point_calibrations"},
                "scope_breakdown": {"type": "object", "description": "Counts by scope: point, equipment, type, bootstrap"},
                "sample_details": {"type": "array", "description": "Representative subset or filtered details of active calibrations"}
            }
        }
    },
    {
        "name": "probe_bacnet_point",
        "description": (
            "Probe a single BACnet point for metadata (object type, unit, current "
            "value, age). Read-only — no side effects. Use to inspect a candidate "
            "before discovery/registration, or to answer 'what is this point?' queries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "point_id": {
                    "type": "string",
                    "description": "Canonical point id, e.g. 'CH-02/FLT_DP'."
                }
            },
            "required": ["point_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:point_probe"],
        "response_schema": {
            "type": "object",
            "properties": {
                "point_id": {"type": "string"},
                "found": {"type": "boolean"},
                "metadata": {"type": "object"}
            }
        }
    },
    {
        "name": "register_point_to_poller",
        "description": (
            "Register a discovered BACnet point into the ARVIS runtime poll "
            "registry via the Discovery Agent. Performs criticality classification, "
            "rate-limit + safety checks, and signs the action into the audit log. "
            "Writable points on critical equipment (CH-*, FIRE-*, FACP-*, ELEV-*, "
            "LS-*) require operator approval and will NOT auto-register. New points "
            "enter a 24h probation window (read but excluded from alarms)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "point_id": {
                    "type": "string",
                    "description": "Canonical point id, e.g. 'CH-02/FLT_DP'."
                },
                "cadence_seconds": {
                    "type": "number",
                    "description": "Optional cadence override; classifier picks one if omitted."
                },
                "priority": {
                    "type": "string",
                    "description": "Optional priority override: critical | nice_to_have | cosmetic."
                }
            },
            "required": ["point_id"]
        },
        "version": "1.0.0",
        "cost_class": "moderate",
        "precedents": [],
        "produces": ["evidence:discovery_decision"],
        "response_schema": {
            "type": "object",
            "properties": {
                "point_id": {"type": "string"},
                "registered": {"type": "boolean"},
                "requires_operator_approval": {"type": "boolean"},
                "reason": {"type": "string"},
                "classification": {"type": "object"},
                "audit_entry_id": {"type": "string"}
            }
        }
    },
    {
        "name": "list_discovery_candidates",
        "description": (
            "Return a ranked list of unmapped BACnet points that look CRITICAL by "
            "the rule-based classifier. Use this to preview what the Discovery "
            "Agent would auto-onboard during a scheduled scan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max candidates to return. Default 20.",
                    "default": 20
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:discovery_candidates"],
        "response_schema": {
            "type": "object",
            "properties": {
                "candidates": {"type": "array"},
                "total_unmapped": {"type": "integer"}
            }
        }
    },
    {
        "name": "audit_discovery_log",
        "description": (
            "Query the signed, tamper-evident Discovery Agent audit log. Returns "
            "the most recent discovery actions (register, quarantine, rate_limited, "
            "operator_approval_required, etc.). Use for forensic review of "
            "autonomous onboarding behaviour."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Optional equipment filter, e.g. 'CH-04'."
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries. Default 100.",
                    "default": 100
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:discovery_audit"],
        "response_schema": {
            "type": "object",
            "properties": {
                "entries": {"type": "array"},
                "chain_verified": {"type": "boolean"}
            }
        }
    },
    {
        "name": "exclude_unreliable_sensor",
        "description": "Exclude a broken or noisy sensor data point from future ARVIS analysis and alarms. Suppresses telemetry updates for this point in the digital twin.",
        "parameters": {
            "type": "object",
            "properties": {
                "point_id": {
                    "type": "string",
                    "description": "Canonical point id (e.g. 'CT-02/VIB_RMS')."
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for sensor exclusion / suppression."
                }
            },
            "required": ["point_id", "reason"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:point_exclusion"],
        "response_schema": {
            "type": "object",
            "properties": {
                "point_id": {"type": "string"},
                "excluded": {"type": "boolean"},
                "message": {"type": "string"}
            }
        }
    },
    {
        "name": "get_year_end_summary",
        "description": "Retrieve an honest consolidated year-end summary of ARVIS's operational metrics, adoption rates, false-alarm suppressions, and economic value delivered over the past year.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_window_days": {
                    "type": "integer",
                    "description": "Window of summary in days (default: 365)."
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:year_end_summary"],
        "response_schema": {
            "type": "object",
            "properties": {
                "adoption_rate": {"type": "number"},
                "false_positives_count": {"type": "number"},
                "fp_cost_qar": {"type": "number"},
                "unrealized_savings_qar": {"type": "number"},
                "catastrophic_save_value_qar": {"type": "number"},
                "honest_assessment": {"type": "string"}
            }
        }
    },
    {
        "name": "get_false_positive_cost_ledger",
        "description": "Retrieve the false-positive cost ledger for predictive maintenance, comparing actual dispatch analysis costs against estimated costs of missing a real bearing failure.",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "required": [],
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:cost_ledger"],
        "response_schema": {
            "type": "object",
            "properties": {
                "cost_of_being_wrong_qar": {"type": "number"},
                "cost_of_missing_real_failure_min_qar": {"type": "number"},
                "cost_of_missing_real_failure_max_qar": {"type": "number"},
                "preventive_savings_qar": {"type": "number"},
                "expected_value_math": {"type": "string"}
            }
        }
    },
]

