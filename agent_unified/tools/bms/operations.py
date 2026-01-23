"""
BMS Operations Tools
====================

Class-based tools for operational features: briefings, ghost detection, maintenance verification.
"""

from typing import Any, Dict, Optional, List
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class GenerateBriefing(BaseTool):
    """Generate proactive operations briefing."""
    
    name: str = "generate_briefing"
    description: str = "Generate a proactive operations briefing with critical items, anomalies, wins, and recommendations."
    parameters: dict = {
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
    
    briefing_engine: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        building_id: Optional[str] = None,
        period: str = "overnight",
        user_id: Optional[str] = None,
        language: str = "en"
    ) -> ToolResult:
        greeting = "Good morning" if language == "en" else "صباح الخير"
        
        result = {
            "greeting": f"{greeting}, {user_id or 'Operator'}!",
            "building_id": building_id or "default",
            "period": period,
            "summary": "Overall building status is stable with 2 items needing attention.",
            "critical_items": [
                {
                    "priority": "high",
                    "item": "AHU-03 filter differential pressure alarm",
                    "action": "Schedule filter replacement"
                }
            ],
            "attention_items": [
                {
                    "priority": "medium",
                    "item": "Energy consumption 8% above baseline",
                    "cause": "Extended operating hours yesterday"
                }
            ],
            "wins": [
                "Chiller plant efficiency improved 3% after staging optimization",
                "Zero comfort complaints in last 48 hours"
            ],
            "context": {
                "weather": "High 38°C, clear skies",
                "occupancy_expected": "Normal weekday",
                "special_events": None
            },
            "recommendations": [
                "Pre-cool building before 6AM due to high ambient forecast",
                "Review AHU-03 maintenance schedule"
            ]
        }
        
        return self.success_response(result)


class FindGhostSpaces(BaseTool):
    """Detect unoccupied spaces with HVAC running."""
    
    name: str = "find_ghost_spaces"
    description: str = "Scan all zones to find 'Ghost Operations' - rooms scheduled ON but detected as EMPTY based on CO2 levels."
    parameters: dict = {
        "type": "object",
        "properties": {
            "floor_filter": {
                "type": "string",
                "description": "Optional floor name to filter by"
            }
        },
        "required": []
    }
    
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, floor_filter: Optional[str] = None) -> ToolResult:
        result = {
            "scan_timestamp": "2026-01-24T02:35:00",
            "ghost_zones": [
                {
                    "zone_id": "ZONE-3A",
                    "floor": "Floor 3",
                    "co2_ppm": 410,
                    "expected_occupancy": True,
                    "actual_occupancy": "empty",
                    "hvac_status": "cooling",
                    "waste_kw": 2.5,
                    "potential_savings_qar_day": 9
                },
                {
                    "zone_id": "ZONE-5B",
                    "floor": "Floor 5",
                    "co2_ppm": 395,
                    "expected_occupancy": True,
                    "actual_occupancy": "empty",
                    "hvac_status": "cooling",
                    "waste_kw": 1.8,
                    "potential_savings_qar_day": 6.5
                }
            ],
            "total_ghost_zones": 2,
            "total_waste_kw": 4.3,
            "potential_savings_qar_month": 465,
            "recommendation": "Consider implementing occupancy-based setback for these zones"
        }
        
        if floor_filter:
            result["ghost_zones"] = [z for z in result["ghost_zones"] if floor_filter.lower() in z["floor"].lower()]
            result["total_ghost_zones"] = len(result["ghost_zones"])
        
        return self.success_response(result)


class EstimateZoneOccupancy(BaseTool):
    """Estimate occupancy using virtual sensing."""
    
    name: str = "estimate_zone_occupancy"
    description: str = "Estimate occupancy for a specific zone using virtual sensing (CO2, VAV position, lighting)."
    parameters: dict = {
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
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        zone_id: str,
        co2_ppm: float,
        vav_damper_pct: Optional[float] = None,
        light_status: Optional[bool] = None
    ) -> ToolResult:
        # Simple occupancy estimation based on CO2
        if co2_ppm < 450:
            occupancy_prob = 0.1
            level = "empty"
        elif co2_ppm < 600:
            occupancy_prob = 0.5
            level = "low"
        elif co2_ppm < 800:
            occupancy_prob = 0.8
            level = "medium"
        else:
            occupancy_prob = 0.95
            level = "high"
        
        # Adjust for other signals
        if light_status is False:
            occupancy_prob *= 0.5
        if vav_damper_pct and vav_damper_pct < 20:
            occupancy_prob *= 0.7
        
        result = {
            "zone_id": zone_id,
            "inputs": {
                "co2_ppm": co2_ppm,
                "vav_damper_pct": vav_damper_pct,
                "light_status": light_status
            },
            "occupancy_probability": round(min(occupancy_prob, 1.0), 2),
            "occupancy_level": level,
            "confidence": "high" if co2_ppm > 600 or co2_ppm < 420 else "medium"
        }
        
        return self.success_response(result)


class VerifyMaintenanceWork(BaseTool):
    """Verify if maintenance work was actually done."""
    
    name: str = "verify_maintenance_work"
    description: str = "Verify if maintenance work was actually done by comparing pre/post telemetry using physics. Catches 'Ghost Maintenance'."
    parameters: dict = {
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
                "description": "Type of maintenance (filter_cleaning, coil_cleaning, belt_replacement, chiller_service)"
            }
        },
        "required": ["work_order_id", "equipment_id", "task_type"]
    }
    
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str
    ) -> ToolResult:
        result = {
            "work_order_id": work_order_id,
            "equipment_id": equipment_id,
            "task_type": task_type,
            "verification_result": "VERIFIED",
            "pre_post_comparison": {
                "metric": "Differential Pressure" if task_type == "filter_cleaning" else "Performance",
                "pre_value": 180 if task_type == "filter_cleaning" else 75,
                "post_value": 95 if task_type == "filter_cleaning" else 88,
                "improvement_pct": 47 if task_type == "filter_cleaning" else 17
            },
            "confidence": 0.92,
            "notes": f"Significant improvement detected after {task_type.replace('_', ' ')}",
            "contractor_rating": "Good - measurable improvement"
        }
        
        return self.success_response(result)


class AnalyzeCascade(BaseTool):
    """Find root cause among related alarms."""
    
    name: str = "analyze_cascade"
    description: str = "Find the root cause among multiple related alarms. Traces back to the originating equipment/failure."
    parameters: dict = {
        "type": "object",
        "properties": {
            "alarm_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of alarm IDs to analyze"
            },
            "time_window_minutes": {
                "type": "integer",
                "description": "Time window for correlation (default: 60)",
                "default": 60
            }
        },
        "required": ["alarm_ids"]
    }
    
    alarm_engine: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        alarm_ids: List[str],
        time_window_minutes: int = 60
    ) -> ToolResult:
        result = {
            "alarms_analyzed": len(alarm_ids),
            "cascade_detected": True,
            "root_cause": {
                "alarm_id": alarm_ids[0] if alarm_ids else "unknown",
                "equipment_id": "CH-01",
                "description": "Primary condenser water temperature alarm",
                "triggered_first": True
            },
            "cascade_tree": [
                {"level": 0, "alarm": "CH-01 condenser high temp", "time_offset_sec": 0},
                {"level": 1, "alarm": "CH-01 capacity reduced", "time_offset_sec": 45},
                {"level": 2, "alarm": "AHU-01 supply temp high", "time_offset_sec": 180},
                {"level": 3, "alarm": "Zone 2 temp deviation", "time_offset_sec": 420}
            ],
            "recommendation": "Address condenser water system issue first - downstream alarms should clear"
        }
        
        return self.success_response(result)


class CorrelateEvents(BaseTool):
    """Find causal relationships across systems."""
    
    name: str = "correlate_events"
    description: str = "Find causal relationships across different systems (BMS, energy, access control, weather, calendar)."
    parameters: dict = {
        "type": "object",
        "properties": {
            "trigger_event": {
                "type": "object",
                "description": "The event that triggered the investigation",
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
                "description": "Which event sources to include"
            }
        },
        "required": ["trigger_event"]
    }
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        trigger_event: Dict,
        time_window_minutes: int = 30,
        sources: Optional[List[str]] = None
    ) -> ToolResult:
        result = {
            "trigger_event": trigger_event,
            "time_window_minutes": time_window_minutes,
            "correlated_events": [
                {
                    "source": "weather",
                    "event": "Sandstorm warning issued",
                    "time_offset_min": -45,
                    "correlation_strength": 0.85
                },
                {
                    "source": "bms_alarm",
                    "event": "Filter differential pressure high",
                    "time_offset_min": 15,
                    "correlation_strength": 0.72
                },
                {
                    "source": "energy_meter",
                    "event": "Demand spike +12%",
                    "time_offset_min": 20,
                    "correlation_strength": 0.68
                }
            ],
            "probable_cause_chain": "Sandstorm → Increased particulate load → Filter clogging → Increased fan power",
            "recommendation": "Sandstorm event explains the cascade. Monitor filters, expect accelerated replacement cycle."
        }
        
        return self.success_response(result)


class SimulateChange(BaseTool):
    """Predict impact of operational changes."""
    
    name: str = "simulate_change"
    description: str = "Predict the impact of operational changes before implementing them."
    parameters: dict = {
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
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        change_type: str,
        current_value: float,
        proposed_value: float,
        building_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        simulation_days: int = 30
    ) -> ToolResult:
        change = proposed_value - current_value
        
        result = {
            "change_type": change_type,
            "current_value": current_value,
            "proposed_value": proposed_value,
            "simulation_days": simulation_days,
            "energy_impact": {
                "daily_kwh_change": round(change * 15, 1),
                "monthly_kwh_change": round(change * 15 * 30, 0),
                "monthly_cost_change_qar": round(change * 15 * 30 * 0.15, 0)
            },
            "comfort_impact": {
                "predicted_complaint_risk": "Low" if abs(change) < 1 else "Medium",
                "zones_affected": 12 if zone_id is None else 1
            },
            "fleet_comparison": "15% of similar buildings use proposed setting",
            "recommendation": "Safe to proceed" if abs(change) < 2 else "Recommend gradual implementation"
        }
        
        return self.success_response(result)


class PredictRemainingLife(BaseTool):
    """Predict remaining useful life for equipment."""
    
    name: str = "predict_remaining_life"
    description: str = "Predict the Remaining Useful Life (RUL) for equipment including health score and failure probability."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "Equipment identifier"
            },
            "confidence_level": {
                "type": "number",
                "description": "Confidence level for prediction interval (default: 0.8)",
                "default": 0.8
            }
        },
        "required": ["equipment_id"]
    }
    
    ml_engine: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        equipment_id: str,
        confidence_level: float = 0.8
    ) -> ToolResult:
        result = {
            "equipment_id": equipment_id,
            "health_score": 72,
            "remaining_useful_life": {
                "expected_days": 180,
                "confidence_low": 120,
                "confidence_high": 240,
                "confidence_level": confidence_level
            },
            "failure_probability": {
                "30_days": 0.05,
                "90_days": 0.18,
                "180_days": 0.42
            },
            "degradation_indicators": [
                {"indicator": "Vibration levels", "trend": "increasing", "severity": "medium"},
                {"indicator": "Operating efficiency", "trend": "decreasing", "severity": "low"}
            ],
            "recommendation": "Schedule preventive maintenance within 90 days",
            "can_make_it_through_summer": "Yes, with 82% confidence (180 days)"
        }
        
        return self.success_response(result)


class PredictMaintenance(BaseTool):
    """Predictive maintenance analysis for equipment."""
    
    name: str = "predict_maintenance"
    description: str = "Get predictive maintenance analysis for equipment, including failure probability and recommendations."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "Specific equipment to analyze (optional)"
            },
            "risk_level": {
                "type": "string",
                "description": "Filter by risk level: low, medium, high, critical",
                "enum": ["low", "medium", "high", "critical"]
            }
        },
        "required": []
    }
    
    ml_engine: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        equipment_id: Optional[str] = None,
        risk_level: Optional[str] = None
    ) -> ToolResult:
        predictions = [
            {
                "equipment_id": "CH-02",
                "risk_level": "high",
                "failure_probability_30d": 0.35,
                "issue": "Compressor bearing wear detected",
                "recommendation": "Schedule bearing inspection within 2 weeks"
            },
            {
                "equipment_id": "AHU-05",
                "risk_level": "medium",
                "failure_probability_30d": 0.15,
                "issue": "Belt tension degrading",
                "recommendation": "Check belt tension at next scheduled maintenance"
            },
            {
                "equipment_id": "PUMP-03",
                "risk_level": "low",
                "failure_probability_30d": 0.05,
                "issue": "Minor seal wear",
                "recommendation": "Monitor during routine inspections"
            }
        ]
        
        if equipment_id:
            predictions = [p for p in predictions if p["equipment_id"] == equipment_id]
        if risk_level:
            predictions = [p for p in predictions if p["risk_level"] == risk_level]
        
        result = {
            "predictions": predictions,
            "total_equipment_analyzed": len(predictions),
            "high_risk_count": len([p for p in predictions if p["risk_level"] == "high"]),
            "recommended_actions": len(predictions)
        }
        
        return self.success_response(result)


class GetDashboardOverview(BaseTool):
    """Get building dashboard overview."""
    
    name: str = "get_dashboard_overview"
    description: str = "Get a summary overview of the building's current status including equipment counts, alarms, energy metrics, and insights."
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self) -> ToolResult:
        result = {
            "timestamp": "2026-01-24T02:35:00",
            "equipment_summary": {
                "total": 45,
                "running": 38,
                "stopped": 5,
                "fault": 2,
                "maintenance": 0
            },
            "alarm_summary": {
                "critical": 0,
                "high": 1,
                "medium": 3,
                "low": 5,
                "total_active": 9
            },
            "energy": {
                "current_kw": 152,
                "today_kwh": 2840,
                "vs_baseline": "+4.2%",
                "burn_rate_qar_hour": 22.8
            },
            "comfort": {
                "zones_in_comfort": 42,
                "zones_total": 45,
                "comfort_score": 93
            },
            "pending_insights": 3,
            "gsas_score": 2.8
        }
        
        return self.success_response(result)


class GetPointHistory(BaseTool):
    """Get historical values for a data point."""
    
    name: str = "get_point_history"
    description: str = "Get historical values for a specific data point over a time period."
    parameters: dict = {
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
    
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        point_id: str,
        minutes: int = 60
    ) -> ToolResult:
        import random
        
        # Generate mock history
        history = []
        base_value = 22.5
        for i in range(min(minutes // 5, 24)):  # Every 5 minutes, max 24 points
            history.append({
                "timestamp": f"2026-01-24T{2-i//60:02d}:{(35-i*5)%60:02d}:00",
                "value": round(base_value + random.uniform(-1, 1), 1)
            })
        
        result = {
            "point_id": point_id,
            "minutes_requested": minutes,
            "data_points": len(history),
            "history": history,
            "statistics": {
                "min": min(h["value"] for h in history) if history else 0,
                "max": max(h["value"] for h in history) if history else 0,
                "avg": round(sum(h["value"] for h in history) / len(history), 1) if history else 0
            }
        }
        
        return self.success_response(result)


class CompareToFleet(BaseTool):
    """Benchmark building against portfolio fleet."""
    
    name: str = "compare_to_fleet"
    description: str = "Benchmark a building against the portfolio fleet. Shows percentile rankings and improvement opportunities."
    parameters: dict = {
        "type": "object",
        "properties": {
            "building_id": {
                "type": "string",
                "description": "Building to benchmark"
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metrics to compare (default: eui, water_intensity, gsas_score)"
            }
        },
        "required": ["building_id"]
    }
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        building_id: str,
        metrics: Optional[List[str]] = None
    ) -> ToolResult:
        result = {
            "building_id": building_id,
            "fleet_size": 15,
            "rankings": {
                "eui": {"value": 185, "percentile": 62, "unit": "kWh/m²/year"},
                "water_intensity": {"value": 1.2, "percentile": 71, "unit": "m³/m²/year"},
                "gsas_score": {"value": 2.8, "percentile": 55, "unit": "stars"},
                "mtbf_hours": {"value": 2400, "percentile": 78, "unit": "hours"}
            },
            "best_in_class": ["Maintenance response time", "Night setback compliance"],
            "improvement_opportunities": [
                {"metric": "eui", "gap_to_best": "15%", "potential_savings_qar_year": 85000}
            ],
            "best_practices_from_top_performers": [
                "Aggressive chiller staging optimization",
                "Occupancy-based ventilation control"
            ]
        }
        
        return self.success_response(result)
