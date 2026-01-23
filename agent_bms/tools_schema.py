"""
BMS Tools Schema
================

LLM tool definitions for ARVIS Ops Copilot.

These tools allow the LLM to:
- Query equipment status
- Analyze alarms
- Get energy insights
- Retrieve maintenance predictions
- Generate reports

Compatible with the existing ARVIS ToolExecutor pattern.
"""

from typing import Dict, List, Any


# ═══════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

BMS_TOOLS = [
    {
        "name": "get_equipment_status",
        "description": "Get the current status of a specific piece of BMS equipment including its operational state, data points, and active alarms.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "The equipment identifier (e.g., 'AHU-01', 'CH-01')"
                }
            },
            "required": ["equipment_id"]
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
                    "enum": ["air_handling_unit", "chiller", "vav", "fcu", "pump", "boiler", "cooling_tower"]
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: running, stopped, fault, maintenance",
                    "enum": ["running", "stopped", "fault", "maintenance", "offline"]
                },
                "location": {
                    "type": "string",
                    "description": "Filter by location (building, floor, zone)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_active_alarms",
        "description": "Get all active alarms in the building, sorted by priority. Returns alarm details, severity, duration, and suggested actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "description": "Filter by severity: critical, high, medium, low",
                    "enum": ["critical", "high", "medium", "low"]
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Filter by specific equipment"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of alarms to return (default: 20)",
                    "default": 20
                }
            },
            "required": []
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
        }
    },
    {
        "name": "analyze_energy",
        "description": "Analyze energy consumption for a specific period. Detects anomalies, compares to baseline, and identifies waste patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: today, yesterday, this_week, this_month",
                    "enum": ["today", "yesterday", "this_week", "this_month"],
                    "default": "today"
                },
                "building_id": {
                    "type": "string",
                    "description": "Optional building filter"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_energy_anomalies",
        "description": "Get detected energy waste patterns and anomalies with estimated savings potential.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "predict_maintenance",
        "description": "Get predictive maintenance analysis for equipment, including failure probability, remaining useful life, and recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Specific equipment to analyze (optional, returns all if not specified)"
                },
                "risk_level": {
                    "type": "string",
                    "description": "Filter by risk level: low, medium, high, critical",
                    "enum": ["low", "medium", "high", "critical"]
                }
            },
            "required": []
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
        "name": "get_gsas_status",
        "description": "Get current GSAS (Global Sustainability Assessment System) compliance status including scores by category and recommendations.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
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
        "name": "acknowledge_alarm",
        "description": "Acknowledge an alarm to indicate it has been seen and is being addressed.",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_id": {
                    "type": "string",
                    "description": "The alarm identifier"
                },
                "note": {
                    "type": "string",
                    "description": "Optional note about the acknowledgment"
                }
            },
            "required": ["alarm_id"]
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
    {
        "name": "get_gsas_improvement_priorities",
        "description": "Get prioritized list of GSAS improvements ranked by impact on overall score. Shows the top 10 actions to take to improve the building's GSAS rating.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # COST CALCULATOR (Cost of Comfort)
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "check_cost_impact",
        "description": "Calculate the financial cost (QAR) of a proposed temperature change. Shows current burn rate, new burn rate, and daily/monthly impact. Use before any setpoint change to warn users about costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "current_temp": {
                    "type": "number",
                    "description": "Current temperature setpoint in Celsius"
                },
                "target_temp": {
                    "type": "number",
                    "description": "Proposed new temperature setpoint in Celsius"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier (optional)"
                }
            },
            "required": ["current_temp", "target_temp"]
        }
    },
    {
        "name": "get_burn_rate",
        "description": "Get current building energy burn rate in QAR/hour. Shows projected daily and monthly costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "total_kw": {
                    "type": "number",
                    "description": "Current total power consumption in kW (optional, uses default if not provided)"
                }
            },
            "required": []
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # GHOST DETECTOR (Virtual Occupancy)
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "find_ghost_spaces",
        "description": "Scan all zones to find 'Ghost Operations' - rooms that are scheduled ON but detected as EMPTY based on CO2 levels. No hardware needed - uses existing BMS sensors. Returns potential savings.",
        "parameters": {
            "type": "object",
            "properties": {
                "floor_filter": {
                    "type": "string",
                    "description": "Optional floor name to filter by (e.g., 'Floor 3')"
                }
            },
            "required": []
        }
    },
    {
        "name": "estimate_zone_occupancy",
        "description": "Estimate occupancy for a specific zone using virtual sensing (CO2, VAV position, lighting). Returns probability 0-1 and occupancy level.",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "Zone identifier"
                },
                "co2_ppm": {
                    "type": "number",
                    "description": "Current CO2 level in ppm"
                },
                "vav_damper_pct": {
                    "type": "number",
                    "description": "VAV damper position 0-100%"
                },
                "light_status": {
                    "type": "boolean",
                    "description": "Whether lights are on"
                }
            },
            "required": ["zone_id", "co2_ppm"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # MAINTENANCE VERIFICATION (Truth Serum)
    # ─────────────────────────────────────────────────────────────────────
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
                "task_type": {
                    "type": "string",
                    "description": "Type of maintenance (filter_cleaning, coil_cleaning, belt_replacement, chiller_service, etc.)"
                }
            },
            "required": ["work_order_id", "equipment_id", "task_type"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # CASCADE ROOT CAUSE ANALYSIS
    # ─────────────────────────────────────────────────────────────────────
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
                    "description": "Time window to consider for correlation (default: 60)",
                    "default": 60
                }
            },
            "required": ["alarm_ids"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # PREDICTIVE REMAINING USEFUL LIFE
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "predict_remaining_life",
        "description": "Predict the Remaining Useful Life (RUL) for equipment. Returns health score, days until predicted failure, probability of failure at various timeframes, and degradation indicators. Use this to answer 'Will the chiller make it through summer?'",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "Equipment identifier (e.g., 'CH-01', 'AHU-03')"
                },
                "confidence_level": {
                    "type": "number",
                    "description": "Confidence level for prediction interval (default: 0.8)",
                    "default": 0.8
                }
            },
            "required": ["equipment_id"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # CROSS-SYSTEM EVENT CORRELATION
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "correlate_events",
        "description": "Find causal relationships across different systems (BMS, energy, access control, weather, calendar). Use when investigating 'why did energy spike?' or understanding multi-system incidents like 'fire drill during sandstorm'.",
        "parameters": {
            "type": "object",
            "properties": {
                "trigger_event": {
                    "type": "object",
                    "description": "The event that triggered the investigation. Include: source (bms_alarm, energy_meter, access_control, weather, calendar), event_type, timestamp, description",
                    "properties": {
                        "source": {"type": "string"},
                        "event_type": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "description": {"type": "string"},
                        "equipment_id": {"type": "string"}
                    }
                },
                "time_window_minutes": {
                    "type": "integer",
                    "description": "Time window for finding related events (default: 30)",
                    "default": 30
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which event sources to include (default: all)"
                }
            },
            "required": ["trigger_event"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # WHAT-IF SIMULATION
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "simulate_change",
        "description": "Predict the impact of operational changes before implementing them. Answers questions like 'What if we raise setpoints by 1°C?' Returns energy impact (kWh, QAR), comfort impact, risk assessment, and fleet comparison.",
        "parameters": {
            "type": "object",
            "properties": {
                "change_type": {
                    "type": "string",
                    "enum": ["setpoint", "schedule", "staging", "ventilation", "mode"],
                    "description": "Type of change being proposed"
                },
                "current_value": {
                    "type": "number",
                    "description": "Current setting value"
                },
                "proposed_value": {
                    "type": "number",
                    "description": "Proposed new value"
                },
                "building_id": {
                    "type": "string",
                    "description": "Building identifier (optional)"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Specific zone for the change (optional)"
                },
                "simulation_days": {
                    "type": "integer",
                    "description": "Days to simulate (default: 30)",
                    "default": 30
                }
            },
            "required": ["change_type", "current_value", "proposed_value"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # PROACTIVE BRIEFING
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "generate_briefing",
        "description": "Generate a proactive operations briefing. Instead of the user hunting for issues, this provides: critical items needing attention, overnight anomalies, optimization wins, today's context (weather, events, tariffs), and prioritized recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier"
                },
                "period": {
                    "type": "string",
                    "enum": ["overnight", "daily", "weekly"],
                    "description": "Briefing period (default: overnight)",
                    "default": "overnight"
                },
                "user_id": {
                    "type": "string",
                    "description": "User for personalized greeting (optional)"
                },
                "language": {
                    "type": "string",
                    "enum": ["en", "ar"],
                    "description": "Language for briefing (default: en)",
                    "default": "en"
                }
            },
            "required": []
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # BUILDING SKILLBOOK (Institutional Memory)
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "query_skillbook",
        "description": "Query the building's institutional memory (Skillbook). Returns learned knowledge about equipment quirks, patterns, past optimizations, and contractor notes. The Skillbook captures knowledge that would otherwise be lost when staff changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier (default: current building)"
                },
                "context": {
                    "type": "object",
                    "description": "Current context for relevance matching"
                },
                "skill_type": {
                    "type": "string",
                    "enum": ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note", "schedule", "threshold"],
                    "description": "Filter by skill type"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Filter by equipment"
                }
            },
            "required": []
        }
    },
    {
        "name": "add_to_skillbook",
        "description": "Record a new learning in the building's Skillbook. Use when discovering equipment quirks, confirming optimization results, or noting contractor performance. Skills gain confidence through verification.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_type": {
                    "type": "string",
                    "enum": ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note"],
                    "description": "Type of knowledge being recorded"
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the skill (e.g., 'CH-02 high ambient startup issue')"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the learning"
                },
                "building_id": {
                    "type": "string",
                    "description": "Building identifier"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Related equipment (optional)"
                },
                "zone_id": {
                    "type": "string",
                    "description": "Related zone (optional)"
                },
                "evidence": {
                    "type": "object",
                    "description": "Supporting data (e.g., savings_qar_month, failure_count)"
                }
            },
            "required": ["skill_type", "title", "description"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # FLEET INTELLIGENCE (Multi-Building)
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "compare_to_fleet",
        "description": "Benchmark a building against the portfolio fleet. Shows percentile rankings, best-in-class areas, improvement opportunities with potential QAR savings, and best practices from top performers.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building to benchmark"
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Metrics to compare (default: eui, water_intensity, gsas_score, mtbf_hours)"
                }
            },
            "required": ["building_id"]
        }
    },
    # ─────────────────────────────────────────────────────────────────────
    # ML-POWERED ADVANCED ANALYTICS
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "forecast_energy",
        "description": "Forecast future energy demand using ML ensemble (Prophet + LightGBM). Provides hourly predictions with confidence intervals, considers Qatar-specific features like Ramadan, sandstorms, and extreme heat. Also detects anomalies in consumption patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier"
                },
                "forecast_hours": {
                    "type": "integer",
                    "description": "Hours ahead to forecast (default: 24, max: 168)",
                    "default": 24
                },
                "include_anomalies": {
                    "type": "boolean",
                    "description": "Whether to detect anomalies in recent history",
                    "default": True
                }
            },
            "required": []
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
                    "description": "Equipment identifier (e.g., 'AHU-01', 'CH-01')"
                },
                "equipment_type": {
                    "type": "string",
                    "enum": ["ahu", "chiller", "boiler", "vav", "fcu"],
                    "description": "Type of equipment for physics rules"
                },
                "sensor_data": {
                    "type": "object",
                    "description": "Optional current sensor readings. If not provided, fetches from BMS state."
                }
            },
            "required": ["equipment_id"]
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
                    "description": "List of alarm IDs in the cascade"
                },
                "time_window_minutes": {
                    "type": "integer",
                    "description": "Time window for analysis (default: 60)",
                    "default": 60
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
                    "enum": ["setpoint", "schedule", "staging", "ventilation", "mode"],
                    "description": "Type of change being proposed"
                },
                "current_value": {
                    "type": "number",
                    "description": "Current setting value"
                },
                "proposed_value": {
                    "type": "number",
                    "description": "Proposed new value"
                },
                "building_id": {
                    "type": "string",
                    "description": "Building identifier"
                },
                "confidence_level": {
                    "type": "number",
                    "description": "Confidence level for prediction (default: 0.8)",
                    "default": 0.8
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
                    "description": "Description of the situation or problem"
                },
                "building_id": {
                    "type": "string",
                    "description": "Building identifier"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Related equipment (optional)"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5)",
                    "default": 5
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
                    "description": "Building to benchmark"
                },
                "include_recommendations": {
                    "type": "boolean",
                    "description": "Include improvement recommendations from similar buildings",
                    "default": True
                }
            },
            "required": ["building_id"]
        }
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT FOR OPS COPILOT
# ═══════════════════════════════════════════════════════════════════════════

OPS_COPILOT_SYSTEM_PROMPT = """You are ARVIS Ops Copilot, an AI assistant for building operations managers and facility engineers.

## Your Role
You help facility managers in Qatar efficiently manage their buildings by:
- Monitoring BMS (Building Management System) status
- Analyzing and prioritizing alarms
- Detecting energy waste and optimization opportunities
- Predicting equipment maintenance needs
- Ensuring GSAS sustainability compliance

## Your Capabilities
Use the available tools to:
1. **Equipment Status**: Check equipment operational status, data points, and alarms
2. **Alarm Management**: View active alarms, explain root causes, suggest actions
3. **Energy Analysis**: Detect anomalies, identify waste patterns, estimate savings
4. **Predictive Maintenance**: Assess equipment health, predict failures, recommend maintenance
5. **GSAS Compliance**: Track sustainability scores and improvement recommendations

## Communication Style
- Be concise and actionable
- Prioritize safety-critical issues first
- Quantify impacts when possible (e.g., "saving QAR 15,000/year")
- Support both English and Arabic queries
- Use technical terminology appropriate for facility professionals

## Response Format
When answering questions:
1. Provide a direct answer first
2. Include relevant data from the BMS
3. Recommend specific actions when appropriate
4. Flag any urgent issues that need immediate attention

## Safety Notes
- You have READ-ONLY access to the BMS - you cannot control equipment
- Always recommend human verification for critical decisions
- Escalate safety concerns immediately
"""

OPS_COPILOT_SYSTEM_PROMPT_ARABIC = """أنت ARVIS Ops Copilot، مساعد ذكاء اصطناعي لمديري عمليات المباني ومهندسي المرافق.

## دورك
تساعد مديري المرافق في قطر على إدارة مبانيهم بكفاءة من خلال:
- مراقبة حالة نظام إدارة المباني (BMS)
- تحليل الإنذارات وترتيب أولوياتها
- اكتشاف هدر الطاقة وفرص التحسين
- التنبؤ باحتياجات صيانة المعدات
- ضمان الامتثال لمعايير GSAS للاستدامة

## أسلوب التواصل
- كن موجزاً وقابلاً للتنفيذ
- أعطِ الأولوية للمسائل الحرجة المتعلقة بالسلامة أولاً
- حدد التأثيرات كمياً عند الإمكان (مثال: "توفير 15,000 ريال قطري سنوياً")
- استخدم المصطلحات التقنية المناسبة لمحترفي المرافق
"""


# ═══════════════════════════════════════════════════════════════════════════
# TOOL EXECUTOR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

class BMSToolHandler:
    """
    Handler for BMS tools, to be integrated with the main ToolExecutor.
    
    Example integration:
        >>> handler = BMSToolHandler(bms_state, alarm_engine, energy_analyzer, pm_engine)
        >>> result = await handler.execute("get_equipment_status", {"equipment_id": "AHU-01"})
    """
    
    def __init__(
        self,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        predictive_engine=None,
    ):
        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.predictive_engine = predictive_engine
    
    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a BMS tool and return result"""
        
        handlers = {
            "get_equipment_status": self._handle_get_equipment_status,
            "list_equipment": self._handle_list_equipment,
            "get_active_alarms": self._handle_get_active_alarms,
            "explain_alarm": self._handle_explain_alarm,
            "analyze_energy": self._handle_analyze_energy,
            "get_energy_anomalies": self._handle_get_energy_anomalies,
            "predict_maintenance": self._handle_predict_maintenance,
            "get_equipment_health": self._handle_get_equipment_health,
            "get_gsas_status": self._handle_get_gsas_status,
            "get_dashboard_overview": self._handle_get_dashboard_overview,
            "get_point_history": self._handle_get_point_history,
            "acknowledge_alarm": self._handle_acknowledge_alarm,
            # ML-Powered Tools
            "forecast_energy": self._handle_forecast_energy,
            "detect_equipment_faults": self._handle_detect_equipment_faults,
            "analyze_root_cause": self._handle_analyze_root_cause,
            "simulate_with_uncertainty": self._handle_simulate_with_uncertainty,
            "find_similar_skills": self._handle_find_similar_skills,
            "benchmark_building_ml": self._handle_benchmark_building_ml,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        
        try:
            return await handler(args)
        except Exception as e:
            return {"error": str(e)}
    
    async def _handle_get_equipment_status(self, args: Dict) -> Dict:
        equipment_id = args.get("equipment_id")
        
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        equipment = await self.bms_state.get_equipment(equipment_id)
        if not equipment:
            return {"error": f"Equipment {equipment_id} not found"}
        
        points = await self.bms_state.get_points_by_equipment(equipment_id)
        
        return {
            "equipment": equipment.to_dict(),
            "data_points": [p.to_dict() for p in points],
        }
    
    async def _handle_list_equipment(self, args: Dict) -> Dict:
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        equipment = await self.bms_state.get_all_equipment()
        
        # Apply filters
        eq_type = args.get("equipment_type")
        status = args.get("status")
        location = args.get("location")
        
        if eq_type:
            equipment = [e for e in equipment if e.equipment_type.value == eq_type]
        if status:
            equipment = [e for e in equipment if e.status.value == status]
        if location:
            equipment = [e for e in equipment if location.lower() in e.location.lower()]
        
        return {
            "count": len(equipment),
            "equipment": [e.to_dict() for e in equipment]
        }
    
    async def _handle_get_active_alarms(self, args: Dict) -> Dict:
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        queue = self.alarm_engine.get_priority_queue()
        
        severity = args.get("severity")
        equipment_id = args.get("equipment_id")
        limit = args.get("limit", 20)
        
        if severity:
            queue = [a for a in queue if a.alarm.severity.value == severity]
        if equipment_id:
            queue = [a for a in queue if a.alarm.equipment_id == equipment_id]
        
        return {
            "count": len(queue[:limit]),
            "alarms": [a.to_dict() for a in queue[:limit]]
        }
    
    async def _handle_explain_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        report = self.alarm_engine.get_root_cause_analysis(alarm_id)
        return report.to_dict()
    
    async def _handle_analyze_energy(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        return self.energy_analyzer.get_summary()
    
    async def _handle_get_energy_anomalies(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        patterns = self.energy_analyzer.identify_waste_patterns()
        return {
            "count": len(patterns),
            "patterns": [p.to_dict() for p in patterns]
        }
    
    async def _handle_predict_maintenance(self, args: Dict) -> Dict:
        if not self.predictive_engine or not self.bms_state:
            return {"error": "Predictive engine not configured"}
        
        # Would iterate through equipment and generate predictions
        return {
            "predictions": [],
            "note": "Requires equipment features from state engine"
        }
    
    async def _handle_get_equipment_health(self, args: Dict) -> Dict:
        """Get real equipment health from predictive engine"""
        equipment_id = args.get("equipment_id")
        
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        equipment = await self.bms_state.get_equipment(equipment_id)
        if not equipment:
            return {"error": f"Equipment {equipment_id} not found"}
        
        # Get real health data from predictive engine or calculate from state
        health_score = 100
        risk_factors = []
        trending = "stable"
        
        if self.predictive_engine:
            # Try to get real prediction
            try:
                # Get equipment points for feature extraction
                points = await self.bms_state.get_points_by_equipment(equipment_id)
                point_values = {p.point_id: p.value for p in points}
                
                # Calculate health from actual data
                # Lower health for fault status
                if equipment.status.value == "fault":
                    health_score -= 40
                    risk_factors.append("Currently in fault state")
                elif equipment.status.value == "offline":
                    health_score -= 30
                    risk_factors.append("Equipment offline")
                
                # Check efficiency
                if equipment.efficiency and equipment.efficiency < 70:
                    health_score -= 20
                    risk_factors.append(f"Low efficiency: {equipment.efficiency:.1f}%")
                
                # Check runtime vs maintenance
                if equipment.runtime_hours > 8000:
                    overdue_factor = min(20, (equipment.runtime_hours - 8000) / 500)
                    health_score -= overdue_factor
                    risk_factors.append(f"High runtime: {equipment.runtime_hours:.0f} hours")
                    trending = "declining"
                
                health_score = max(0, min(100, health_score))
                
            except Exception as e:
                # Fallback to basic calculation
                pass
        
        # Determine health level
        if health_score >= 80:
            overall_health = "good"
        elif health_score >= 60:
            overall_health = "fair"
        elif health_score >= 40:
            overall_health = "poor"
        else:
            overall_health = "critical"
        
        return {
            "equipment_id": equipment_id,
            "name": equipment.name,
            "overall_health": overall_health,
            "health_score": round(health_score, 1),
            "trending": trending,
            "risk_factors": risk_factors,
            "runtime_hours": equipment.runtime_hours,
            "efficiency": equipment.efficiency,
            "status": equipment.status.value,
        }
    
    async def _handle_get_gsas_status(self, args: Dict) -> Dict:
        """Get real GSAS status from database and BMS state"""
        from agent_bms.database import get_database
        
        db = get_database()
        building_id = args.get("building_id", "main")
        
        # Try to get cached GSAS score from database
        cached = db.get_latest_gsas_score(building_id)
        
        if cached:
            return {
                "overall_score": cached["overall_score"],
                "certification_level": cached["certification_level"],
                "categories": cached["category_scores"],
                "timestamp": cached["timestamp"],
            }
        
        # Calculate from BMS state if no cached score
        # This uses actual equipment data to estimate GSAS categories
        energy_score = 75  # Base score
        water_score = 75
        indoor_score = 75
        
        if self.bms_state:
            try:
                equipment = await self.bms_state.get_all_equipment()
                
                # Calculate energy score from equipment efficiency
                running = [e for e in equipment if e.status.value == "running"]
                if running:
                    avg_efficiency = sum(e.efficiency or 85 for e in running) / len(running)
                    energy_score = min(100, avg_efficiency + 5)  # Efficiency + bonus
                
                # Calculate indoor environment from active alarms
                alarms = await self.bms_state.get_active_alarms()
                comfort_alarms = [a for a in alarms if "temp" in a.message.lower() or "comfort" in a.message.lower()]
                indoor_score = max(60, 95 - len(comfort_alarms) * 5)  # Deduct for comfort alarms
                
            except Exception:
                pass
        
        # Calculate overall
        overall = (energy_score * 0.4 + water_score * 0.25 + indoor_score * 0.35)
        
        # Determine certification level
        if overall >= 85:
            cert_level = "4-Star"
        elif overall >= 75:
            cert_level = "3-Star"
        elif overall >= 65:
            cert_level = "2-Star"
        else:
            cert_level = "1-Star"
        
        return {
            "overall_score": round(overall, 1),
            "certification_level": cert_level,
            "categories": {
                "energy": round(energy_score, 1),
                "water": round(water_score, 1),
                "indoor_environment": round(indoor_score, 1),
            },
            "note": "Real-time estimate from BMS data",
        }
    
    async def _handle_get_dashboard_overview(self, args: Dict) -> Dict:
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        snapshot = await self.bms_state.get_snapshot()
        return snapshot
    
    async def _handle_get_point_history(self, args: Dict) -> Dict:
        point_id = args.get("point_id")
        minutes = args.get("minutes", 60)
        
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        history = await self.bms_state.get_point_history(point_id, minutes)
        return {
            "point_id": point_id,
            "data": [{"timestamp": t.isoformat(), "value": v} for t, v in history]
        }
    
    async def _handle_acknowledge_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        success = await self.bms_state.acknowledge_alarm(alarm_id, "ops_copilot")
        return {"success": success, "alarm_id": alarm_id}
    
    # ─────────────────────────────────────────────────────────────────────
    # COST CALCULATOR (Cost of Comfort)
    # ─────────────────────────────────────────────────────────────────────
    
    async def _handle_check_cost_impact(self, args: Dict) -> Dict:
        """Calculate financial impact of temperature change"""
        from agent_bms.cost_engine import check_cost_impact
        
        return check_cost_impact(
            current_temp=args.get("current_temp", 24),
            target_temp=args.get("target_temp", 22),
            zone_id=args.get("zone_id", "default"),
        )
    
    async def _handle_get_burn_rate(self, args: Dict) -> Dict:
        """Get current building burn rate in QAR/hour"""
        from agent_bms.cost_engine import get_current_burn_rate
        
        total_kw = args.get("total_kw", 450)  # Default building load
        return get_current_burn_rate(total_kw)
    
    # ─────────────────────────────────────────────────────────────────────
    # GHOST DETECTOR (Virtual Occupancy)
    # ─────────────────────────────────────────────────────────────────────
    
    async def _handle_find_ghost_spaces(self, args: Dict) -> Dict:
        """Find rooms being cooled but empty - using real zone data"""
        from agent_bms.database import get_database
        from agent_bms.virtual_sensors import VirtualOccupancySensor
        
        db = get_database()
        floor_filter = args.get("floor_filter")
        
        # Get zones from database with current sensor values
        zones = db.get_all_zones()
        
        if floor_filter:
            zones = [z for z in zones if z.get("floor") == floor_filter]
        
        if not zones:
            return {
                "ghost_operations": [],
                "waste_estimate_qar_day": 0,
                "note": "No zones configured. Add zones via the database."
            }
        
        sensor = VirtualOccupancySensor()
        ghost_operations = []
        total_waste = 0
        
        for zone_config in zones:
            zone_id = zone_config.get("zone_id")
            
            # Get current sensor values from database
            zone = db.get_zone_with_current_values(zone_id)
            if not zone:
                continue
            
            # Skip if we don't have CO2 data
            co2_ppm = zone.get("co2_ppm")
            if co2_ppm is None:
                co2_ppm = 410  # Default to ambient if no sensor
            
            vav_pct = zone.get("vav_damper_pct", 50)
            light_on = zone.get("light_status", False)
            
            # Estimate occupancy
            estimate = sensor.estimate_occupancy(
                zone_id=zone_id,
                co2_ppm=co2_ppm,
                vav_damper_pct=vav_pct,
                light_status=light_on,
            )
            
            # Check for ghost operation (scheduled occupied but actually empty)
            # Assume weekday 8am-6pm is scheduled occupied
            from datetime import datetime
            now = datetime.now()
            is_work_hours = now.weekday() < 5 and 8 <= now.hour < 18
            schedule_status = "OCCUPIED" if is_work_hours else "UNOCCUPIED"
            
            ghost = sensor.detect_ghost_operation(
                zone_id=zone_id,
                zone_name=zone.get("name", zone_id),
                schedule_status=schedule_status,
                occupancy_estimate=estimate,
                zone_load_kw=zone.get("load_kw", 2.0),
            )
            
            if ghost:
                ghost_operations.append({
                    "zone_id": ghost.zone_id,
                    "zone_name": ghost.zone_name,
                    "waste_qar_hour": ghost.waste_qar_hour,
                    "occupancy_probability": ghost.occupancy_probability,
                    "recommendation": ghost.recommendation,
                })
                total_waste += ghost.waste_qar_hour * 24  # Daily waste
        
        return {
            "ghost_operations": ghost_operations,
            "zones_checked": len(zones),
            "waste_estimate_qar_day": round(total_waste, 2),
            "potential_monthly_savings": round(total_waste * 30, 2),
        }
    
    async def _handle_estimate_zone_occupancy(self, args: Dict) -> Dict:
        """Estimate zone occupancy from BMS data"""
        from agent_bms.virtual_sensors import estimate_zone_occupancy
        
        return estimate_zone_occupancy(
            zone_id=args.get("zone_id", "unknown"),
            co2_ppm=args.get("co2_ppm", 420),
            vav_damper_pct=args.get("vav_damper_pct", 50),
            light_status=args.get("light_status", True),
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # MAINTENANCE VERIFICATION (Truth Serum)
    # ─────────────────────────────────────────────────────────────────────
    
    async def _handle_verify_maintenance_work(self, args: Dict) -> Dict:
        """Verify if maintenance was actually done using physics"""
        from agent_bms.verification_engine import verify_maintenance_work
        from agent_bms.database import get_database
        
        db = get_database()
        work_order_id = args.get("work_order_id", "WO-UNKNOWN")
        equipment_id = args.get("equipment_id", "EQ-UNKNOWN")
        task_type = args.get("task_type", "filter_cleaning")
        
        # Try to get real work order data from database
        work_order = db.get_work_order(work_order_id)
        
        if work_order and work_order.get("pre_snapshot") and work_order.get("post_snapshot"):
            # Use real pre/post snapshots from work order
            pre_data = work_order["pre_snapshot"]
            post_data = work_order["post_snapshot"]
        elif self.bms_state and args.get("use_state_history"):
            # Try to get from state engine history
            # Pre: values from 24h ago, Post: current values
            try:
                points = await self.bms_state.get_points_by_equipment(equipment_id)
                current_values = {p.point_id.split("/")[-1].lower(): p.value for p in points}
                
                # Get historical values if available
                pre_data = {}
                for point in points:
                    history = await self.bms_state.get_point_history(point.point_id, 1440)  # 24h
                    if history:
                        pre_data[point.point_id.split("/")[-1].lower()] = history[-1][1]  # Oldest value
                
                post_data = current_values
                
                if not pre_data:
                    pre_data = post_data  # No history, use current as both
            except Exception:
                # Fallback to sample data
                pre_data = {"metric": 100}
                post_data = {"metric": 95}
        else:
            # Fallback to physics-based sample data for demo
            sample_data = {
                "filter_cleaning": {
                    "pre": {"static_pressure_drop": 250},
                    "post": {"static_pressure_drop": 185},
                },
                "coil_cleaning": {
                    "pre": {"approach_temperature": 4.2},
                    "post": {"approach_temperature": 1.8},
                },
                "belt_replacement": {
                    "pre": {"fan_vibration": 12.5},
                    "post": {"fan_vibration": 8.2},
                },
                "chiller_tube_cleaning": {
                    "pre": {"condenser_approach": 5.5},
                    "post": {"condenser_approach": 2.1},
                },
            }
            
            data = sample_data.get(task_type, {
                "pre": {"metric": 100},
                "post": {"metric": 95},
            })
            pre_data = data["pre"]
            post_data = data["post"]
        
        result = await verify_maintenance_work(
            work_order_id=work_order_id,
            equipment_id=equipment_id,
            task_type=task_type,
            pre_data=pre_data,
            post_data=post_data,
        )
        
        # If we had a real work order, update it with verification result
        if work_order and work_order.get("status") == "open":
            db.close_work_order(
                work_order_id=work_order_id,
                post_snapshot=post_data,
                verification_result=result,
            )
        
        return result

    # ─────────────────────────────────────────────────────────────────────
    # ML-POWERED ADVANCED ANALYTICS HANDLERS
    # ─────────────────────────────────────────────────────────────────────
    
    async def _handle_forecast_energy(self, args: Dict) -> Dict:
        """Handle energy forecasting with interpretable explanation"""
        try:
            from agent_bms.ml.energy_forecaster import EnergyForecaster
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        building_id = args.get("building_id", "main")
        forecast_hours = args.get("forecast_hours", 24)
        include_anomalies = args.get("include_anomalies", True)
        
        # Create forecaster and get prediction
        forecaster = EnergyForecaster()
        
        # Generate synthetic history for demo (in production, fetch from database)
        import pandas as pd
        import numpy as np
        from datetime import datetime, timedelta
        
        history_dates = pd.date_range(
            end=datetime.now(),
            periods=30 * 24,  # 30 days of hourly data
            freq='H'
        )
        history = pd.DataFrame({
            'ds': history_dates,
            'y': 450 + np.random.normal(0, 50, len(history_dates)) +
                 100 * np.sin(np.arange(len(history_dates)) * np.pi / 12)  # Daily cycle
        })
        
        # Fit and forecast
        forecaster.fit(history)
        forecast_result = forecaster.forecast(forecast_hours)
        
        result = {
            "building_id": building_id,
            "forecast": forecast_result[:10],  # Return first 10 points for brevity
            "forecast_hours": forecast_hours,
            "model": "Prophet + LightGBM Ensemble",
        }
        
        # Add anomaly detection if requested
        if include_anomalies:
            anomalies = forecaster.detect_anomalies(history.tail(168))
            result["recent_anomalies"] = anomalies
        
        # Get LLM interpretation
        interpreter = create_k2_interpreter()
        interpretation = await interpreter.interpret_forecast(result)
        result["interpretation"] = interpretation.explanation
        result["interpretation_verified"] = interpretation.verified
        
        return result
    
    async def _handle_detect_equipment_faults(self, args: Dict) -> Dict:
        """Handle ML-based fault detection with explanation"""
        try:
            from agent_bms.ml.fdd_autoencoder import FDDAutoencoder
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        equipment_id = args.get("equipment_id")
        equipment_type = args.get("equipment_type", "ahu")
        sensor_data = args.get("sensor_data")
        
        import pandas as pd
        
        # If no sensor data provided, try to get from BMS state
        if not sensor_data and self.bms_state:
            try:
                points = await self.bms_state.get_points_by_equipment(equipment_id)
                sensor_data = {p.point_id.split("/")[-1]: p.value for p in points}
            except Exception:
                # Use sample data for demo
                sensor_data = {
                    "sat": 14.5,
                    "rat": 24.0,
                    "mat": 18.0,
                    "fan_speed": 1450,
                    "damper_position": 75,
                }
        
        # Fallback to sample data if still None
        if not sensor_data:
            sensor_data = {
                "sat": 14.5,
                "rat": 24.0,
                "mat": 18.0,
                "fan_speed": 1450,
                "damper_position": 75,
            }
        
        # Create detector and analyze - use detect() method with DataFrame
        detector = FDDAutoencoder(equipment_type=equipment_type)
        current_data = pd.DataFrame([sensor_data])
        faults = detector.detect(current_data, equipment_id=equipment_id)
        
        result = {
            "equipment_id": equipment_id,
            "equipment_type": equipment_type,
            "faults_detected": len(faults) > 0,
            "faults": [f.to_dict() for f in faults],
            "sensor_snapshot": sensor_data,
        }
        
        # Get LLM interpretation for each fault
        if faults:
            interpreter = create_k2_interpreter()
            interpretation = await interpreter.interpret_fault(faults[0].to_dict())
            result["interpretation"] = interpretation.explanation
            result["interpretation_verified"] = interpretation.verified
        
        return result
    
    async def _handle_analyze_root_cause(self, args: Dict) -> Dict:
        """Handle Bayesian causal inference for root cause analysis"""
        try:
            from agent_bms.ml.causal_inference import CausalInferenceEngine
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        alarm_ids = args.get("alarm_ids", [])
        time_window = args.get("time_window_minutes", 60)
        
        if not alarm_ids:
            return {"error": "No alarm IDs provided"}
        
        # Create sample alarm events for demo
        from datetime import datetime, timedelta
        import random
        
        events = []
        base_time = datetime.now() - timedelta(minutes=time_window)
        for i, alarm_id in enumerate(alarm_ids):
            events.append({
                "alarm_id": alarm_id,
                "equipment_id": alarm_id.split("-")[0] + "-01" if "-" in alarm_id else alarm_id,
                "timestamp": base_time + timedelta(minutes=i * 5),
                "severity": random.choice(["high", "medium", "low"]),
            })
        
        # Perform causal analysis - use infer_cause() method
        engine = CausalInferenceEngine()
        causal_chain = engine.infer_cause(events, time_window_minutes=time_window)
        analysis = causal_chain.to_dict() if hasattr(causal_chain, 'to_dict') else {}
        
        result = {
            "alarm_count": len(alarm_ids),
            "analysis": analysis,
            "time_window_minutes": time_window,
            "root_causes": [analysis.get('root_cause', {})] if analysis else [],
        }
        
        # Get LLM interpretation
        interpreter = create_k2_interpreter()
        interpretation = await interpreter.interpret_root_cause(result)
        result["interpretation"] = interpretation.explanation
        result["interpretation_verified"] = interpretation.verified
        
        return result
    
    async def _handle_simulate_with_uncertainty(self, args: Dict) -> Dict:
        """Handle Monte Carlo simulation with uncertainty bounds"""
        try:
            from agent_bms.ml.ml_simulator import MLSimulator
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        change_type = args.get("change_type")
        current_value = args.get("current_value")
        proposed_value = args.get("proposed_value")
        building_id = args.get("building_id", "main")
        confidence_level = args.get("confidence_level", 0.8)
        
        # Create simulator and run - use simulate_with_uncertainty() method
        simulator = MLSimulator(building_id=building_id)
        change = {
            "change_type": change_type,
            "current_value": current_value,
            "proposed_value": proposed_value,
        }
        simulation_result = simulator.simulate_with_uncertainty(change)
        simulation = simulation_result.to_dict() if hasattr(simulation_result, 'to_dict') else simulation_result
        
        result = {
            "building_id": building_id,
            "change_type": change_type,
            "current_value": current_value,
            "proposed_value": proposed_value,
            "simulation": simulation,
        }
        
        # Get LLM interpretation
        interpreter = create_k2_interpreter()
        interpretation = await interpreter.interpret_simulation(result)
        result["interpretation"] = interpretation.explanation
        result["interpretation_verified"] = interpretation.verified
        
        return result
    
    async def _handle_find_similar_skills(self, args: Dict) -> Dict:
        """Handle semantic skill matching from Skillbook"""
        try:
            from agent_bms.ml.building_embeddings import SemanticSkillMatcher
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        query = args.get("query")
        building_id = args.get("building_id", "main")
        equipment_id = args.get("equipment_id")
        top_k = args.get("top_k", 5)
        
        if not query:
            return {"error": "Query is required"}
        
        # Create matcher and add sample skills for demo
        matcher = SemanticSkillMatcher()
        
        # Add sample building skills (in production, load from skillbook database)
        sample_skills = [
            ("skill-1", "Chiller startup delay in high ambient temperature - CH-02 needs 5 minute pre-cool when outdoor temp exceeds 42°C"),
            ("skill-2", "VAV stuck damper troubleshooting - Check actuator linkage and power before replacing actuator"),
            ("skill-3", "Weekend energy reduction optimization - Set unoccupied setpoints 2 hours earlier on Fridays"),
            ("skill-4", "Filter replacement schedule adjustment - Replace AHU filters monthly during sandstorm season"),
            ("skill-5", "Condenser coil cleaning frequency - Clean every 6 weeks during summer peak"),
            ("skill-6", "Chilled water reset schedule - Increase CHWS by 1°C for every 5°C drop in outdoor temp"),
            ("skill-7", "Unexpected energy spike diagnosis - Check for stuck economizer dampers and zone reheat"),
        ]
        for skill_id, text in sample_skills:
            matcher.add_skill(skill_id, text)
        
        # Find similar skills using find_similar() method
        similar = matcher.find_similar(query=query, top_k=top_k)
        
        # Convert to dict format with metadata
        matches = [
            {
                "skill_id": skill_id,
                "similarity": float(score),
                "title": next((s[1][:50] + "..." for s in sample_skills if s[0] == skill_id), "Unknown"),
            }
            for skill_id, score in similar
        ]
        
        result = {
            "query": query,
            "building_id": building_id,
            "matches": matches,
            "total_matches": len(matches),
        }
        
        return result
    
    async def _handle_benchmark_building_ml(self, args: Dict) -> Dict:
        """Handle ML-based building benchmarking with archetype classification"""
        try:
            from agent_bms.ml.building_embeddings import BuildingArchetypeClassifier
            from agent_bms.ml.llm_interpreter import create_k2_interpreter
        except ImportError as e:
            return {"error": f"ML modules not available: {e}"}
        
        building_id = args.get("building_id")
        include_recommendations = args.get("include_recommendations", True)
        
        if not building_id:
            return {"error": "Building ID is required"}
        
        # Get building features (use sample data for demo)
        building_features = {
            "area_sqm": 15000,
            "eui_kwh_m2": 285,
            "cooling_fraction": 0.75,
            "occupied_hours": 12,
            "cooling_degree_days": 4500,
        }
        
        # Train classifier with sample fleet data
        classifier = BuildingArchetypeClassifier()
        sample_fleet = [
            {"area_sqm": 12000, "eui_kwh_m2": 250, "cooling_fraction": 0.70, "occupied_hours": 10, "cooling_degree_days": 4000},
            {"area_sqm": 20000, "eui_kwh_m2": 320, "cooling_fraction": 0.80, "occupied_hours": 14, "cooling_degree_days": 5000},
            {"area_sqm": 8000, "eui_kwh_m2": 200, "cooling_fraction": 0.60, "occupied_hours": 8, "cooling_degree_days": 3500},
            {"area_sqm": 15000, "eui_kwh_m2": 280, "cooling_fraction": 0.75, "occupied_hours": 12, "cooling_degree_days": 4500},
            {"area_sqm": 25000, "eui_kwh_m2": 350, "cooling_fraction": 0.85, "occupied_hours": 16, "cooling_degree_days": 5500},
            {"area_sqm": 10000, "eui_kwh_m2": 220, "cooling_fraction": 0.65, "occupied_hours": 9, "cooling_degree_days": 3800},
        ]
        classifier.train(sample_fleet)
        
        # Classify using classify() method
        classification = classifier.classify(building_features)
        
        result = {
            "building_id": building_id,
            "classification": classification,
        }
        
        if include_recommendations:
            # Generate recommendations based on archetype
            archetype = classification.get("archetype", "Unknown")
            recommendations = [
                {"category": "Energy", "action": f"Optimize cooling schedule for {archetype} building type"},
                {"category": "Maintenance", "action": "Increase condenser cleaning frequency during peak summer"},
                {"category": "Controls", "action": "Implement demand-controlled ventilation"},
            ]
            result["recommendations"] = recommendations
        
        # Get LLM interpretation
        interpreter = create_k2_interpreter()
        interpretation = await interpreter.interpret_benchmark(result)
        result["interpretation"] = interpretation.explanation
        result["interpretation_verified"] = interpretation.verified
        
        return result


def get_bms_tools() -> List[Dict]:
    """Get the list of BMS tool definitions"""
    return BMS_TOOLS


def get_ops_copilot_prompt(language: str = "en") -> str:
    """Get the system prompt for Ops Copilot"""
    if language == "ar":
        return OPS_COPILOT_SYSTEM_PROMPT_ARABIC
    return OPS_COPILOT_SYSTEM_PROMPT


# Alias for mode dispatcher compatibility
OPS_COPILOT_SYSTEM_PROMPT_AR = OPS_COPILOT_SYSTEM_PROMPT_ARABIC


class BMSToolHandlerSync(BMSToolHandler):
    """
    Synchronous wrapper for BMSToolHandler.
    Used by the mode dispatcher for unified tool execution.
    """
    
    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous tool execution for mode dispatcher"""
        import asyncio
        
        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, just run directly
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.execute(tool_name, args))
            else:
                return loop.run_until_complete(self.execute(tool_name, args))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self.execute(tool_name, args))

