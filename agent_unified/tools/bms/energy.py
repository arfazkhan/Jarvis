"""
BMS Energy Tools
================

Class-based tools for energy analysis and optimization.
"""

from typing import Any, Optional
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class AnalyzeEnergy(BaseTool):
    """Analyze energy consumption for a period."""
    
    name: str = "analyze_energy"
    description: str = "Analyze energy consumption for a specific period. Detects anomalies, compares to baseline, and identifies waste patterns."
    parameters: dict = {
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
    
    energy_analyzer: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        period: str = "today",
        building_id: Optional[str] = None
    ) -> ToolResult:
        if not self.energy_analyzer:
            # Return mock data if no analyzer available
            result = {
                "period": period,
                "total_kwh": 12500,
                "cost_qar": 1875,
                "vs_baseline": "+5.2%",
                "status": "above_baseline",
                "anomalies_detected": 2,
                "top_consumers": [
                    {"name": "Chiller Plant", "kwh": 5200, "pct": 41.6},
                    {"name": "AHU Systems", "kwh": 3100, "pct": 24.8},
                    {"name": "Lighting", "kwh": 1800, "pct": 14.4}
                ]
            }
            return self.success_response(result)
        
        try:
            # Use actual analyzer
            analysis = self.energy_analyzer.analyze(period=period, building_id=building_id)
            return self.success_response(analysis)
            
        except Exception as e:
            return self.fail_response(f"Error analyzing energy: {str(e)}")


class GetEnergyAnomalies(BaseTool):
    """Get detected energy waste patterns."""
    
    name: str = "get_energy_anomalies"
    description: str = "Get detected energy waste patterns and anomalies with estimated savings potential."
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    energy_analyzer: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self) -> ToolResult:
        if not self.energy_analyzer:
            # Return mock data
            result = {
                "anomalies": [
                    {
                        "type": "scheduling_waste",
                        "description": "AHU-03 running 2 hours after occupancy end",
                        "equipment": "AHU-03",
                        "savings_potential_qar_month": 1200,
                        "severity": "medium"
                    },
                    {
                        "type": "simultaneous_heating_cooling",
                        "description": "Zone 4B showing both heating and cooling",
                        "equipment": "FCU-4B",
                        "savings_potential_qar_month": 450,
                        "severity": "low"
                    }
                ],
                "total_savings_potential_qar_month": 1650
            }
            return self.success_response(result)
        
        try:
            anomalies = self.energy_analyzer.get_anomalies()
            return self.success_response(anomalies)
            
        except Exception as e:
            return self.fail_response(f"Error getting anomalies: {str(e)}")


class CheckCostImpact(BaseTool):
    """Calculate cost impact of temperature change."""
    
    name: str = "check_cost_impact"
    description: str = "Calculate the financial cost (QAR) of a proposed temperature change. Shows current burn rate, new burn rate, and daily/monthly impact."
    parameters: dict = {
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
    
    energy_analyzer: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        current_temp: float,
        target_temp: float,
        zone_id: Optional[str] = None
    ) -> ToolResult:
        try:
            # Simple cost calculation (can be enhanced with actual analyzer)
            temp_diff = target_temp - current_temp
            
            # ~6% energy change per degree Celsius
            impact_pct = temp_diff * 6.0
            
            # Typical building baseline costs
            baseline_daily_qar = 2500
            
            change_daily_qar = baseline_daily_qar * (impact_pct / 100)
            change_monthly_qar = change_daily_qar * 30
            
            result = {
                "current_setpoint": current_temp,
                "proposed_setpoint": target_temp,
                "temperature_change": temp_diff,
                "energy_impact_pct": round(impact_pct, 1),
                "cost_impact": {
                    "daily_qar": round(change_daily_qar, 2),
                    "monthly_qar": round(change_monthly_qar, 2)
                },
                "recommendation": "Increase cooling" if temp_diff < 0 else "Reduce cooling load",
                "warning": f"This will {'increase' if change_monthly_qar > 0 else 'decrease'} costs by QAR {abs(round(change_monthly_qar))} per month"
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error calculating cost impact: {str(e)}")


class GetBurnRate(BaseTool):
    """Get current energy burn rate."""
    
    name: str = "get_burn_rate"
    description: str = "Get current building energy burn rate in QAR/hour. Shows projected daily and monthly costs."
    parameters: dict = {
        "type": "object",
        "properties": {
            "total_kw": {
                "type": "number",
                "description": "Current total power consumption in kW (optional)"
            }
        },
        "required": []
    }
    
    energy_analyzer: Optional[Any] = None
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, total_kw: Optional[float] = None) -> ToolResult:
        try:
            # Default or get from BMS
            if total_kw is None:
                total_kw = 150  # Default assumption
            
            # Qatar electricity rate (approximately 0.15 QAR/kWh)
            rate_qar_kwh = 0.15
            
            hourly_cost = total_kw * rate_qar_kwh
            daily_cost = hourly_cost * 24
            monthly_cost = daily_cost * 30
            
            result = {
                "current_power_kw": total_kw,
                "electricity_rate_qar_kwh": rate_qar_kwh,
                "burn_rate": {
                    "qar_per_hour": round(hourly_cost, 2),
                    "qar_per_day": round(daily_cost, 2),
                    "qar_per_month": round(monthly_cost, 2)
                },
                "comparison": {
                    "vs_typical_building": "On track" if hourly_cost < 30 else "Above average"
                }
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error calculating burn rate: {str(e)}")
