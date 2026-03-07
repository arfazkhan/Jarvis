"""
Sovereign Cognition Tool Definitions
====================================

Tools for the sovereign cognition layer - skillbook, fleet comparison,
simulation, and cross-system correlation.
"""

SOVEREIGN_TOOLS = [

    {
        "name": "query_skillbook",
        "description": "Query the building's institutional memory (Skillbook). Returns learned knowledge about equipment quirks, patterns, past optimizations, and contractor notes. The Skillbook captures knowledge that would otherwise be lost when staff changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query (e.g., 'AHU-01 startup issues', 'best chiller settings for summer')",
                    "examples": ["How does AHU-01 behave in summer?"]
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Filter by equipment (optional)",
                    "examples": ["AHU-01"]
                },
                "skill_type": {
                    "type": "string",
                    "description": "Filter by type: optimization, quirk, maintenance, contractor, pattern",
                    "enum": ["optimization", "quirk", "maintenance", "contractor", "pattern"],
                    "examples": ["quirk"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 5)",
                    "default": 5,
                    "examples": [3]
                }
            },
            "required": ["query"]
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "skills": {"type": "array"},
                "summary": {"type": "object"}
            }
        }
    },
    {
        "name": "add_to_skillbook",
        "description": "Record a new learning in the building's Skillbook. Use when discovering equipment quirks, confirming optimization results, or noting contractor performance. Skills gain confidence through verification.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the skill"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the learning"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Related equipment (optional)"
                },
                "skill_type": {
                    "type": "string",
                    "description": "Type: optimization, quirk, maintenance, contractor, pattern",
                    "enum": ["optimization", "quirk", "maintenance", "contractor", "pattern"]
                },
                "confidence": {
                    "type": "number",
                    "description": "Initial confidence 0-1 (default: 0.5)",
                    "minimum": 0,
                    "maximum": 1
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for searchability"
                }
            },
            "required": ["title", "description", "skill_type"]
        }
    },
    {
        "name": "compare_to_fleet",
        "description": "Benchmark a building against the portfolio fleet. Shows percentile rankings, best-in-class areas, improvement opportunities with potential QAR savings, and best practices from top performers.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building to compare (optional, uses default)"
                },
                "metric": {
                    "type": "string",
                    "description": "Metric to compare: energy_eui, gsas_score, maintenance_cost, comfort_score",
                    "enum": ["energy_eui", "gsas_score", "maintenance_cost", "comfort_score"]
                }
            },
            "required": []
        }
    },
    {
        "name": "simulate_change",
        "description": "Predict the impact of operational changes before implementing them. Answers questions like 'What if we raise setpoints by 1°C?' Returns energy impact (kWh, QAR), comfort impact, risk assessment, and fleet comparison.",
        "parameters": {
            "type": "object",
            "properties": {
                "change_type": {
                    "type": "string",
                    "description": "Type of change: setpoint_adjustment, schedule_change, equipment_override",
                    "enum": ["setpoint_adjustment", "schedule_change", "equipment_override"],
                    "examples": ["setpoint_adjustment"]
                },
                "target": {
                    "type": "string",
                    "description": "What to change (equipment_id, zone_id, or schedule_name)",
                    "examples": ["AHU-01", "ZONE-A"]
                },
                "current_value": {
                    "type": "number",
                    "description": "Current setting value",
                    "examples": [22.0]
                },
                "proposed_value": {
                    "type": "number",
                    "description": "Proposed new value",
                    "examples": [23.0]
                },
                "duration_hours": {
                    "type": "integer",
                    "description": "How long the change would be in effect (default: 24)",
                    "default": 24,
                    "examples": [8]
                }
            },
            "required": ["change_type", "target", "current_value", "proposed_value"]
        },
        "response_schema": {
            "type": "object",
            "properties": {
                "energy_impact": {"type": "object"},
                "comfort_impact": {"type": "object"},
                "risk_assessment": {"type": "string"}
            }
        }
    },
    {
        "name": "correlate_events",
        "description": "Find causal relationships across different systems (BMS, energy, access control, weather, calendar). Use when investigating 'why did energy spike?' or understanding multi-system incidents like 'fire drill during sandstorm'.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": "Primary event type to investigate"
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range: last_hour, last_24h, last_week",
                    "enum": ["last_hour", "last_24h", "last_week"]
                },
                "correlate_with": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Systems to correlate with: bms, energy, access, weather, calendar"
                },
                "min_correlation": {
                    "type": "number",
                    "description": "Minimum correlation threshold (default: 0.5)",
                    "default": 0.5
                }
            },
            "required": ["event_type"]
        }
    },
]
