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
]
