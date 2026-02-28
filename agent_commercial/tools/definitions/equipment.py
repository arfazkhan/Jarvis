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
        }
    },
    {
        "name": "get_dashboard_overview",
        "description": "Get a summary overview of the building's current status including equipment counts, active alarms, energy metrics, and pending insights.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]
