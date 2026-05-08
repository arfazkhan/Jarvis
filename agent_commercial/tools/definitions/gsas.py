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
        }
    },
]
