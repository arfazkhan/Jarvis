"""
Cost Engine
===========

Real-time operational costing for BMS decisions.

The "Cost of Comfort" Calculator:
- Shows current "Burn Rate" in QAR/hour
- Predicts cost impact of setpoint changes
- GSAS score impact estimation

This turns FMs from "blind operators" into "cost-aware decision makers."

Kahramaa Commercial Electricity Rates (2026):
- Tier 1: 0.13 QAR/kWh (up to 2000 kWh)
- Tier 2: 0.15 QAR/kWh (2001-4000 kWh) 
- Tier 3: 0.18 QAR/kWh (4001-8000 kWh)
- Tier 4: 0.20 QAR/kWh (above 8000 kWh)

Commercial buildings typically operate in Tier 3-4.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("arvis.bms.cost")


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

class KahramaaRate(Enum):
    """Kahramaa electricity rate tiers (QAR/kWh)"""
    TIER_1 = 0.13  # Up to 2000 kWh
    TIER_2 = 0.15  # 2001-4000 kWh
    TIER_3 = 0.18  # 4001-8000 kWh
    TIER_4 = 0.20  # Above 8000 kWh
    COMMERCIAL_AVG = 0.18  # Default for commercial


@dataclass
class CostEstimate:
    """Cost impact estimation result"""
    current_burn_rate_qar_hour: float
    new_burn_rate_qar_hour: float
    change_percent: float
    daily_impact_qar: float
    monthly_impact_qar: float
    gsas_impact_points: float
    recommendation: str
    proceed_warning: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_burn_rate_qar_hour": round(self.current_burn_rate_qar_hour, 2),
            "new_burn_rate_qar_hour": round(self.new_burn_rate_qar_hour, 2),
            "change_percent": round(self.change_percent, 1),
            "daily_impact_qar": round(self.daily_impact_qar, 2),
            "monthly_impact_qar": round(self.monthly_impact_qar, 2),
            "gsas_impact_points": round(self.gsas_impact_points, 1),
            "recommendation": self.recommendation,
            "proceed_warning": self.proceed_warning,
        }
    
    def format_warning(self) -> str:
        """Format as user-friendly warning message"""
        if self.change_percent > 0:
            return (
                f"⚠️ **Cost Warning**\n"
                f"• Current Burn Rate: QAR {self.current_burn_rate_qar_hour:.2f}/hr\n"
                f"• New Burn Rate: QAR {self.new_burn_rate_qar_hour:.2f}/hr (+{self.change_percent:.0f}%)\n"
                f"• Daily Cost Impact: +QAR {self.daily_impact_qar:.2f}\n"
                f"• Monthly Impact: +QAR {self.monthly_impact_qar:.0f}\n"
                f"\n{self.recommendation}"
            )
        else:
            return (
                f"✅ **Cost Savings**\n"
                f"• Current Burn Rate: QAR {self.current_burn_rate_qar_hour:.2f}/hr\n"
                f"• New Burn Rate: QAR {self.new_burn_rate_qar_hour:.2f}/hr ({self.change_percent:.0f}%)\n"
                f"• Daily Savings: QAR {-self.daily_impact_qar:.2f}\n"
            )


# ═══════════════════════════════════════════════════════════════════════════
# COST ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class CostEngine:
    """
    Real-time operational cost calculator.
    
    Features:
    - Current burn rate calculation (QAR/hour)
    - Setpoint change cost prediction
    - GSAS score impact estimation
    - Operating hours cost tracking
    
    Usage:
        >>> engine = CostEngine()
        >>> burn_rate = engine.calculate_burn_rate(current_kw=450)
        >>> print(f"Burning QAR {burn_rate:.2f}/hour")
        
        >>> impact = engine.predict_setpoint_cost(
        ...     current_temp=24, 
        ...     target_temp=21, 
        ...     zone_cfm=5000
        ... )
        >>> print(impact.format_warning())
    """
    
    # Physics constants
    ENERGY_INCREASE_PER_DEGREE_COOLING = 0.08  # 8% per degree C
    ENERGY_INCREASE_PER_DEGREE_HEATING = 0.03  # 3% per degree C (less in Qatar)
    
    # Operating hours
    DEFAULT_OPERATING_HOURS = 12  # 8am-8pm typical
    DAYS_PER_MONTH = 30
    
    def __init__(
        self,
        kwh_rate: float = KahramaaRate.COMMERCIAL_AVG.value,
        operating_hours: int = 12,
    ):
        """
        Initialize cost engine.
        
        Args:
            kwh_rate: Electricity rate in QAR/kWh (default: 0.18)
            operating_hours: Daily operating hours (default: 12)
        """
        self.kwh_rate = kwh_rate
        self.operating_hours = operating_hours
        
        # Historical tracking
        self.hourly_costs: List[Tuple[datetime, float]] = []
        
        logger.info(f"CostEngine initialized: {kwh_rate} QAR/kWh")
    
    def calculate_burn_rate(self, current_kw_load: float) -> float:
        """
        Calculate current cost per hour in QAR.
        
        Args:
            current_kw_load: Current power consumption in kW
            
        Returns:
            Cost in QAR per hour
        """
        return current_kw_load * self.kwh_rate
    
    def calculate_daily_cost(self, current_kw_load: float) -> float:
        """Calculate daily cost based on operating hours"""
        return self.calculate_burn_rate(current_kw_load) * self.operating_hours
    
    def calculate_monthly_cost(self, current_kw_load: float) -> float:
        """Calculate monthly cost estimate"""
        return self.calculate_daily_cost(current_kw_load) * self.DAYS_PER_MONTH
    
    def predict_setpoint_cost(
        self,
        current_temp: float,
        target_temp: float,
        zone_cfm: float = 3000,
        current_load_kw: Optional[float] = None,
    ) -> CostEstimate:
        """
        Estimate the cost impact of a temperature setpoint change.
        
        This is the "Cost of Comfort" calculator - shows FMs the price tag
        of their decisions BEFORE they make them.
        
        Args:
            current_temp: Current temperature setpoint (°C)
            target_temp: Proposed new setpoint (°C)
            zone_cfm: Zone airflow in CFM (for load estimation)
            current_load_kw: Optional current load (auto-estimated if not provided)
            
        Returns:
            CostEstimate with all financial impacts
        """
        delta_t = current_temp - target_temp  # Positive = cooling more
        
        # Estimate base load if not provided
        # Rough rule: 1 CFM ≈ 0.0004 kW average load contribution
        if current_load_kw is None:
            current_load_kw = zone_cfm * 0.0005
        
        # Calculate energy change
        if delta_t > 0:
            # Cooling more (lowering setpoint)
            energy_change_pct = delta_t * self.ENERGY_INCREASE_PER_DEGREE_COOLING
        else:
            # Allowing warmer (raising setpoint) - saves energy
            energy_change_pct = delta_t * self.ENERGY_INCREASE_PER_DEGREE_COOLING
        
        # Calculate new load
        extra_load_kw = current_load_kw * energy_change_pct
        new_load_kw = current_load_kw + extra_load_kw
        
        # Calculate costs
        current_burn = self.calculate_burn_rate(current_load_kw)
        new_burn = self.calculate_burn_rate(new_load_kw)
        
        change_pct = ((new_burn - current_burn) / current_burn * 100) if current_burn > 0 else 0
        daily_impact = (new_burn - current_burn) * self.operating_hours
        monthly_impact = daily_impact * self.DAYS_PER_MONTH
        
        # GSAS impact estimation
        # Energy category is 24% of score, roughly 1 point per 5% energy change
        gsas_impact = -energy_change_pct * 100 / 5 * 0.24
        
        # Generate recommendation
        if delta_t > 2:
            recommendation = (
                f"This will reduce your GSAS Energy Score by ~{abs(gsas_impact):.1f} points. "
                f"Consider a smaller adjustment (22°C) to reduce costs."
            )
            proceed_warning = True
        elif delta_t > 0:
            recommendation = "Moderate impact. Proceed if comfort is critical."
            proceed_warning = False
        else:
            recommendation = "✅ This change will save energy and money!"
            proceed_warning = False
        
        return CostEstimate(
            current_burn_rate_qar_hour=current_burn,
            new_burn_rate_qar_hour=new_burn,
            change_percent=change_pct,
            daily_impact_qar=daily_impact,
            monthly_impact_qar=monthly_impact,
            gsas_impact_points=gsas_impact,
            recommendation=recommendation,
            proceed_warning=proceed_warning,
        )
    
    def get_building_burn_rate(self, total_kw: float) -> Dict[str, Any]:
        """
        Get current building-wide burn rate summary.
        
        This is what shows on the dashboard: "Current Burn Rate: QAR 75.00/hr"
        """
        hourly = self.calculate_burn_rate(total_kw)
        daily = self.calculate_daily_cost(total_kw)
        monthly = self.calculate_monthly_cost(total_kw)
        
        # Track for history
        self.hourly_costs.append((datetime.now(), hourly))
        # Keep only last 24 hours
        cutoff = datetime.now() - timedelta(hours=24)
        self.hourly_costs = [(t, c) for t, c in self.hourly_costs if t > cutoff]
        
        # Calculate trend
        if len(self.hourly_costs) >= 2:
            recent = sum(c for t, c in self.hourly_costs[-6:]) / min(6, len(self.hourly_costs))
            earlier = sum(c for t, c in self.hourly_costs[:6]) / min(6, len(self.hourly_costs))
            trend = "rising" if recent > earlier * 1.05 else "falling" if recent < earlier * 0.95 else "stable"
        else:
            trend = "insufficient_data"
        
        return {
            "current_load_kw": round(total_kw, 1),
            "burn_rate_qar_hour": round(hourly, 2),
            "projected_daily_qar": round(daily, 2),
            "projected_monthly_qar": round(monthly, 0),
            "trend": trend,
            "timestamp": datetime.now().isoformat(),
        }
    
    def calculate_zone_cost(
        self,
        zone_id: str,
        zone_load_kw: float,
        operating_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Calculate cost for a specific zone"""
        hours = operating_hours or self.operating_hours
        hourly = self.calculate_burn_rate(zone_load_kw)
        
        return {
            "zone_id": zone_id,
            "load_kw": round(zone_load_kw, 2),
            "cost_per_hour_qar": round(hourly, 2),
            "cost_per_day_qar": round(hourly * hours, 2),
            "operating_hours": hours,
        }
    
    def compare_setpoints(
        self,
        scenarios: List[Dict[str, float]],
        zone_cfm: float = 3000,
    ) -> List[Dict[str, Any]]:
        """
        Compare multiple setpoint scenarios.
        
        Args:
            scenarios: List of {"temp": 21} dicts
            zone_cfm: Zone airflow
            
        Returns:
            Sorted list of scenarios with costs (cheapest first)
        """
        # Assume current is Qatar comfort standard (24°C)
        current_temp = 24.0
        
        results = []
        for scenario in scenarios:
            target = scenario.get("temp", current_temp)
            estimate = self.predict_setpoint_cost(current_temp, target, zone_cfm)
            results.append({
                "setpoint_c": target,
                "daily_cost_qar": estimate.daily_impact_qar,
                "gsas_impact": estimate.gsas_impact_points,
            })
        
        # Sort by cost
        results.sort(key=lambda x: x["daily_cost_qar"])
        return results


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def check_cost_impact(
    current_temp: float,
    target_temp: float,
    zone_id: str = "default",
    zone_cfm: float = 3000,
) -> Dict[str, Any]:
    """
    Quick function to check cost impact of a temperature change.
    
    This is the LLM tool handler.
    """
    engine = CostEngine()
    estimate = engine.predict_setpoint_cost(current_temp, target_temp, zone_cfm)
    
    return {
        "zone_id": zone_id,
        "current_temp": current_temp,
        "target_temp": target_temp,
        "estimate": estimate.to_dict(),
        "warning_message": estimate.format_warning(),
        "should_warn_user": estimate.proceed_warning,
    }


def get_current_burn_rate(total_kw: float) -> Dict[str, Any]:
    """Get current building burn rate - for dashboard display"""
    engine = CostEngine()
    return engine.get_building_burn_rate(total_kw)
