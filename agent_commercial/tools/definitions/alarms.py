"""
Alarm Tool Definitions
======================

Tools for managing BMS alarms and alerts.
"""

ALARM_TOOLS = [
    {
        "name": "get_active_alarms",
        "description": "Get all active alarms in the building, sorted by priority. Returns alarm details, severity, duration, and suggested actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "description": "Filter by severity: critical, high, medium, low",
                    "enum": ["critical", "high", "medium", "low"],
                    "examples": ["critical"]
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Filter by specific equipment",
                    "examples": ["AHU-01"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of alarms to return (default: 20)",
                    "default": 20,
                    "examples": [10]
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:active_alarms"],
        "response_schema": {
            "type": "object",
            "properties": {
                "alarms": {"type": "array"}
            }
        }
    },
    {
        "name": "explain_alarm",
        "description": "Get detailed explanation and root cause analysis for a specific alarm, including related alarms and recommended actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_id": {
                    "type": "string",
                    "description": "The alarm identifier"
                }
            },
            "required": ["alarm_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_active_alarms"],
        "produces": ["evidence:alarm_explanation"],
        "response_schema": {
            "type": "object",
            "properties": {
                "alarm_id": {"type": "string"},
                "explanation": {"type": "string", "description": "Human-readable explanation of the alarm cause"},
                "root_cause": {"type": "string", "description": "Identified root cause"},
                "related_alarms": {"type": "array", "description": "IDs of correlated alarms"},
                "recommended_actions": {"type": "array", "description": "Ordered list of suggested remediation steps"},
                "severity": {"type": "string"}
            }
        }
    },
    {
        "name": "acknowledge_alarm",
        "description": "Acknowledge an alarm to indicate it has been seen and is being addressed.",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_id": {
                    "type": "string",
                    "description": "The alarm identifier",
                    "examples": ["ALM-2024-001"]
                },
                "note": {
                    "type": "string",
                    "description": "Optional note about the acknowledgment",
                    "examples": ["Investigating AHU-01 high static pressure."]
                }
            },
            "required": ["alarm_id"]
        },
        "requires_confirmation": True,
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_active_alarms"],
        "produces": ["evidence:alarm_acknowledged"],
        "response_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"}
            }
        }
    },
    {
        "name": "analyze_cascade",
        "description": "Find the root cause among multiple related alarms. When many alarms fire at once, this tool traces back to the originating equipment/failure. Returns the cascade tree showing cause-effect relationships.",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of alarm IDs to analyze for cascade relationship"
                },
                "time_window_minutes": {
                    "type": "integer",
                    "description": "Time window to consider for cascade analysis (default: 30)",
                    "default": 30
                }
            },
            "required": ["alarm_ids"]
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_active_alarms"],
        "produces": ["evidence:cascade_analysis"],
        "response_schema": {
            "type": "object",
            "properties": {
                "root_cause_alarm_id": {"type": "string", "description": "The originating alarm in the cascade"},
                "root_cause_equipment": {"type": "string", "description": "Equipment identified as cascade source"},
                "cascade_tree": {"type": "object", "description": "Cause-effect tree of alarm propagation"},
                "confidence": {"type": "number", "description": "Confidence 0-1 in root cause identification"},
                "affected_systems": {"type": "array", "description": "Systems impacted by the cascade"}
            }
        }
    },
    {
        "name": "get_alarm_clusters",
        "description": "Get all active alarm clusters with root cause analysis. Collapses many related alarms into grouped clusters showing the probable root cause equipment, confidence level, affected zones, and member alarms. Use this to understand the real situation behind alarm noise.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": ["get_active_alarms"],
        "produces": ["evidence:alarm_clusters"],
        "response_schema": {
            "type": "object",
            "properties": {
                "cluster_count": {"type": "integer"},
                "total_alarms_collapsed": {"type": "integer"},
                "clusters": {"type": "array"}
            }
        }
    },
]
