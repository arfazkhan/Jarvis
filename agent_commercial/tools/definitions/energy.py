"""
Energy Tool Definitions
=======================

Tools for energy analysis and cost calculations.
"""

ENERGY_TOOLS = [
    {
        "name": "analyze_energy",
        "description": "Analyze energy consumption for a specific period. Detects anomalies, compares to baseline, and identifies waste patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period: today, yesterday, this_week, this_month, next_week",
                    "enum": ["today", "yesterday", "this_week", "this_month", "next_week"],
                    "default": "today",
                    "examples": ["today", "this_week"]
                },
                "building_id": {
                    "type": "string",
                    "description": "Optional building filter",
                    "examples": ["main"]
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:energy_analysis"],
        "response_schema": {
            "type": "object",
            "properties": {
                "total_kwh": {"type": "number"},
                "cost_qar": {"type": "number"},
                "anomalies": {"type": "array"}
            }
        }
    },
    {
        "name": "get_energy_anomalies",
        "description": "Get detected energy waste patterns and anomalies with estimated savings potential.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:energy_anomalies"],
        "response_schema": {
            "type": "object",
            "properties": {
                "anomalies": {"type": "array", "description": "List of detected anomalies with equipment, pattern, and deviation details"},
                "total_waste_kwh": {"type": "number", "description": "Estimated total wasted energy across all anomalies"},
                "potential_savings_qar": {"type": "number", "description": "Estimated monthly savings if anomalies are resolved"},
                "anomaly_count": {"type": "integer"}
            }
        }
    },
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
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:cost_impact"],
        "response_schema": {
            "type": "object",
            "properties": {
                "current_burn_rate_qar_hr": {"type": "number", "description": "Current energy cost per hour in QAR"},
                "new_burn_rate_qar_hr": {"type": "number", "description": "Projected energy cost per hour after change"},
                "daily_impact_qar": {"type": "number", "description": "Net daily cost change (positive = more expensive)"},
                "monthly_impact_qar": {"type": "number"},
                "delta_kwh_per_day": {"type": "number"},
                "recommendation": {"type": "string"}
            }
        }
    },
    {
        "name": "get_burn_rate",
        "description": "Get current building energy burn rate in QAR/hour. Shows projected daily and monthly costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building identifier (optional)"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:burn_rate"],
        "response_schema": {
            "type": "object",
            "properties": {
                "burn_rate_qar_hr": {"type": "number", "description": "Current energy cost per hour in QAR"},
                "burn_rate_kw": {"type": "number", "description": "Current power demand in kW"},
                "projected_daily_qar": {"type": "number"},
                "projected_monthly_qar": {"type": "number"},
                "vs_baseline_pct": {"type": "number", "description": "Percentage above or below daily baseline"}
            }
        }
    },
    {
        "name": "find_ghost_spaces",
        "description": "Scan all zones to find 'Ghost Operations' - rooms that are scheduled ON but detected as EMPTY based on CO2 levels. No hardware needed - uses existing BMS sensors. Returns potential savings.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "Building to scan (optional, defaults to all)"
                }
            },
            "required": []
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:ghost_spaces"],
        "response_schema": {
            "type": "object",
            "properties": {
                "ghost_spaces": {"type": "array", "description": "Zones detected as empty but scheduled on, each with zone_id, scheduled_hours, waste_kwh, and waste_qar"},
                "total_ghost_count": {"type": "integer"},
                "total_waste_kwh_day": {"type": "number"},
                "potential_savings_qar_month": {"type": "number"}
            }
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
                    "description": "Zone identifier (e.g., 'ZONE-F1-01')"
                },
                "method": {
                    "type": "string",
                    "description": "Sensing method: co2 (default), vav, lighting, or fusion (all combined)",
                    "enum": ["co2", "vav", "lighting", "fusion"],
                    "default": "fusion"
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
                "occupancy_probability": {"type": "number", "description": "Probability 0.0-1.0 that zone is occupied"},
                "occupancy_level": {"type": "string", "description": "empty, low, medium, or high"},
                "estimated_occupants": {"type": "integer"},
                "method_used": {"type": "string"},
                "confidence": {"type": "number"}
            }
        }
    },
    {
        "name": "estimate_virtual_sat",
        "description": "Derive supply air temperature for an AHU using existing BMS data — no new temperature sensor needed. Uses energy balance model (mixed air temp + cooling valve + airflow) or zone thermal inference (return air + fan speed) depending on available inputs. Returns estimated SAT in °C with confidence level and method used.",
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "AHU equipment identifier",
                    "examples": ["AHU-01"]
                },
                "mixed_air_temp_c": {
                    "type": "number",
                    "description": "Mixed air temperature at AHU inlet (°C) — preferred input"
                },
                "cooling_valve_pct": {
                    "type": "number",
                    "description": "Cooling coil valve position (0–100%)"
                },
                "airflow_m3h": {
                    "type": "number",
                    "description": "Supply fan airflow rate (m³/h)"
                },
                "rated_cooling_kw": {
                    "type": "number",
                    "description": "AHU rated cooling capacity in kW (default: 50)"
                },
                "return_air_temp_c": {
                    "type": "number",
                    "description": "Return air temperature (°C) — used in fallback inference"
                },
                "fan_speed_pct": {
                    "type": "number",
                    "description": "Supply fan speed (%) — used in fallback inference"
                }
            },
            "required": ["equipment_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:virtual_sat"],
        "response_schema": {
            "type": "object",
            "properties": {
                "estimated_sat_c": {"type": "number"},
                "confidence": {"type": "number"},
                "method": {"type": "string"}
            }
        }
    },
    {
        "name": "get_virtual_sensor_reading",
        "description": "Query any virtual sensor by ID. Returns derived value, confidence, and method used. Use for SAT estimation or zone occupancy when physical sensor data is unavailable.",
        "parameters": {
            "type": "object",
            "properties": {
                "sensor_id": {
                    "type": "string",
                    "description": "Virtual sensor ID (e.g. 'vsat_AHU-01', 'vocc_ZONE-01')"
                },
                "equipment_id": {
                    "type": "string",
                    "description": "Override equipment ID for ad-hoc reads"
                }
            },
            "required": ["sensor_id"]
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": ["get_equipment_status"],
        "produces": ["evidence:virtual_sensor_reading"],
        "response_schema": {
            "type": "object",
            "properties": {
                "sensor_id": {"type": "string"},
                "value": {"type": "number", "description": "Derived sensor value in appropriate engineering units"},
                "unit": {"type": "string"},
                "confidence": {"type": "number", "description": "Confidence 0-1 in derived reading"},
                "method": {"type": "string", "description": "Inference method used (e.g. energy_balance, zone_thermal)"},
                "timestamp": {"type": "string"}
            }
        }
    },
]
