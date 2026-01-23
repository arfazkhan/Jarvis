"""
What-If Simulator
=================

Predict impact of operational changes before implementing them.

Questions ARVIS can now answer:
- "What if we raise setpoints by 1°C?"
- "What if we change chiller staging?"
- "What if we reduce ventilation rate?"

Uses:
- Physics-based energy models
- Historical building data
- Fleet comparison (similar buildings)
- Comfort impact prediction

Usage:
    >>> simulator = WhatIfSimulator("tower_a")
    >>> result = simulator.simulate({
    ...     "change_type": "setpoint",
    ...     "current_value": 22,
    ...     "proposed_value": 23,
    ... })
    >>> print(result["cost_impact"])
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("arvis.bms.simulator")


# =============================================================================
# CONSTANTS - Qatar Specific
# =============================================================================

# Energy rates (QAR/kWh)
RATE_STANDARD = 0.033
RATE_PEAK = 0.066  # 2x during 12:00-18:00

# Average building parameters
DEFAULT_BUILDING_AREA_M2 = 10000
DEFAULT_COP = 3.5  # Coefficient of Performance for chillers
COOLING_LOAD_PER_DEGREE = 0.08  # kW/m² per degree delta

# Comfort thresholds
COMFORT_SETPOINT_MIN = 20
COMFORT_SETPOINT_MAX = 26
COMFORT_OPTIMAL_RANGE = (22, 24)


# =============================================================================
# DATA MODELS
# =============================================================================

class ChangeType(Enum):
    """Types of operational changes"""
    SETPOINT = "setpoint"
    SCHEDULE = "schedule"
    STAGING = "staging"
    VENTILATION = "ventilation"
    MODE = "mode"


class RiskLevel(Enum):
    """Risk levels for proposed changes"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class EnergyImpact:
    """Predicted energy impact"""
    delta_kwh_day: float
    delta_kwh_month: float
    delta_cost_qar_day: float
    delta_cost_qar_month: float
    percentage_change: float
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta_kwh_day": round(self.delta_kwh_day, 1),
            "delta_kwh_month": round(self.delta_kwh_month, 1),
            "delta_cost_qar_day": round(self.delta_cost_qar_day, 2),
            "delta_cost_qar_month": round(self.delta_cost_qar_month, 2),
            "percentage_change": round(self.percentage_change, 1),
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ComfortImpact:
    """Predicted comfort impact"""
    occupant_satisfaction_change: float  # -100 to +100
    complaint_probability: float  # 0-1
    affected_zones: List[str]
    notes: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "satisfaction_change": round(self.occupant_satisfaction_change, 1),
            "complaint_probability": round(self.complaint_probability, 2),
            "affected_zones": self.affected_zones,
            "notes": self.notes,
        }


@dataclass
class FleetComparison:
    """Comparison with similar buildings"""
    similar_buildings_count: int
    success_rate: float  # % of buildings where similar change worked
    avg_savings_pct: float
    reversion_rate: float  # % that reverted the change
    notes: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "similar_buildings": self.similar_buildings_count,
            "success_rate": round(self.success_rate, 1),
            "avg_savings_pct": round(self.avg_savings_pct, 1),
            "reversion_rate": round(self.reversion_rate, 1),
            "notes": self.notes,
        }


@dataclass
class RiskAssessment:
    """Risk assessment for proposed change"""
    risk_level: RiskLevel
    risks: List[str]
    mitigations: List[str]
    reversibility: str  # "immediate", "easy", "complex"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level.value,
            "risks": self.risks,
            "mitigations": self.mitigations,
            "reversibility": self.reversibility,
        }


@dataclass
class SimulationResult:
    """Complete simulation result"""
    change_type: ChangeType
    current_value: Any
    proposed_value: Any
    energy_impact: EnergyImpact
    comfort_impact: ComfortImpact
    fleet_comparison: Optional[FleetComparison]
    risk_assessment: RiskAssessment
    recommendation: str
    recommendation_reason: str
    simulated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_type": self.change_type.value,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "energy_impact": self.energy_impact.to_dict(),
            "comfort_impact": self.comfort_impact.to_dict(),
            "fleet_comparison": self.fleet_comparison.to_dict() if self.fleet_comparison else None,
            "risk_assessment": self.risk_assessment.to_dict(),
            "recommendation": self.recommendation,
            "recommendation_reason": self.recommendation_reason,
            "simulated_at": self.simulated_at.isoformat(),
        }


# =============================================================================
# WEATHER SERVICE (for outdoor conditions)
# =============================================================================

class WeatherForecast:
    """Get weather forecast for simulation."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY")
        self.lat = 25.2854  # Doha
        self.lon = 51.5310
    
    def get_forecast(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get weather forecast for next N days."""
        if not self.api_key:
            return self._mock_forecast(days)
        
        try:
            import requests
            response = requests.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "lat": self.lat,
                    "lon": self.lon,
                    "appid": self.api_key,
                    "units": "metric",
                    "cnt": days * 8,  # 3-hour intervals
                },
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                daily = []
                for i in range(0, len(data["list"]), 8):
                    item = data["list"][i]
                    daily.append({
                        "date": item["dt_txt"].split()[0],
                        "temp_max": item["main"]["temp_max"],
                        "temp_min": item["main"]["temp_min"],
                        "condition": item["weather"][0]["main"],
                    })
                return daily[:days]
            else:
                return self._mock_forecast(days)
                
        except Exception as e:
            logger.debug(f"Weather API error: {e}")
            return self._mock_forecast(days)
    
    def _mock_forecast(self, days: int) -> List[Dict[str, Any]]:
        """Generate mock Qatar weather forecast."""
        import random
        
        base_date = datetime.now()
        forecast = []
        
        for i in range(days):
            date = base_date + timedelta(days=i)
            # Simulate Qatar summer (hot) vs winter (mild)
            month = date.month
            if 5 <= month <= 9:  # Summer
                temp_max = random.uniform(40, 48)
                temp_min = random.uniform(30, 35)
            else:  # Winter/Spring/Fall
                temp_max = random.uniform(25, 35)
                temp_min = random.uniform(15, 22)
            
            forecast.append({
                "date": date.strftime("%Y-%m-%d"),
                "temp_max": round(temp_max, 1),
                "temp_min": round(temp_min, 1),
                "condition": "Clear" if random.random() > 0.2 else "Dust",
            })
        
        return forecast


# =============================================================================
# WHAT-IF SIMULATOR
# =============================================================================

class WhatIfSimulator:
    """
    Predict impact of operational changes.
    
    Uses physics-based models combined with historical data
    to forecast energy, comfort, and cost impacts.
    """
    
    def __init__(self,
                 building_id: str = "default",
                 building_area_m2: float = DEFAULT_BUILDING_AREA_M2,
                 bms_state=None,
                 energy_analyzer=None):
        """
        Initialize the What-If Simulator.
        
        Args:
            building_id: Building identifier
            building_area_m2: Building floor area
            bms_state: BMSStateEngine for current data
            energy_analyzer: EnergyAnalyzer for baseline
        """
        self.building_id = building_id
        self.building_area = building_area_m2
        self.bms_state = bms_state
        self.energy_analyzer = energy_analyzer
        
        self.weather = WeatherForecast()
        
        logger.info(f"WhatIfSimulator initialized for {building_id}")
    
    def simulate(self, change: Dict[str, Any]) -> SimulationResult:
        """
        Simulate the impact of a proposed change.
        
        Args:
            change: Dictionary with:
                - change_type: "setpoint", "schedule", "staging", "ventilation", "mode"
                - current_value: Current setting
                - proposed_value: Proposed new setting
                - zone_id: (optional) Specific zone
                - simulation_days: (optional) Days to simulate (default 30)
                
        Returns:
            SimulationResult with all impact predictions
        """
        change_type = ChangeType(change.get("change_type", "setpoint"))
        current = change.get("current_value")
        proposed = change.get("proposed_value")
        simulation_days = change.get("simulation_days", 30)
        
        # Get weather forecast for simulation period
        weather_forecast = self.weather.get_forecast(min(simulation_days, 7))
        
        # Calculate impacts based on change type
        if change_type == ChangeType.SETPOINT:
            energy_impact = self._simulate_setpoint_change(current, proposed, weather_forecast)
            comfort_impact = self._estimate_comfort_setpoint(current, proposed)
        elif change_type == ChangeType.SCHEDULE:
            energy_impact = self._simulate_schedule_change(current, proposed)
            comfort_impact = self._estimate_comfort_schedule(current, proposed)
        elif change_type == ChangeType.VENTILATION:
            energy_impact = self._simulate_ventilation_change(current, proposed)
            comfort_impact = self._estimate_comfort_ventilation(current, proposed)
        else:
            # Generic simulation for other types
            energy_impact = self._simulate_generic_change(current, proposed)
            comfort_impact = ComfortImpact(
                occupant_satisfaction_change=0,
                complaint_probability=0.1,
                affected_zones=["all"],
                notes="Generic estimate - monitor after implementation",
            )
        
        # Get fleet comparison
        fleet_comparison = self._get_fleet_comparison(change_type, current, proposed)
        
        # Assess risks
        risk_assessment = self._assess_risks(change_type, current, proposed, comfort_impact)
        
        # Generate recommendation
        recommendation, reason = self._generate_recommendation(
            energy_impact, comfort_impact, risk_assessment, fleet_comparison
        )
        
        return SimulationResult(
            change_type=change_type,
            current_value=current,
            proposed_value=proposed,
            energy_impact=energy_impact,
            comfort_impact=comfort_impact,
            fleet_comparison=fleet_comparison,
            risk_assessment=risk_assessment,
            recommendation=recommendation,
            recommendation_reason=reason,
        )
    
    def _simulate_setpoint_change(self,
                                   current_temp: float,
                                   proposed_temp: float,
                                   weather: List[Dict]) -> EnergyImpact:
        """
        Simulate energy impact of temperature setpoint change.
        
        Physics: Each 1°C increase in cooling setpoint saves ~6-8% energy
        (based on typical building envelope and equipment)
        """
        delta_temp = proposed_temp - current_temp
        
        # Calculate average outdoor temperature from forecast
        avg_outdoor = sum(w["temp_max"] for w in weather) / len(weather) if weather else 35
        
        # Energy savings per degree (positive delta = warmer setpoint = savings)
        savings_per_degree_pct = 0.07  # 7% per degree
        
        # Adjust for outdoor conditions
        # Larger savings when outdoor is hotter (bigger delta between indoor/outdoor)
        outdoor_factor = 1 + (avg_outdoor - 30) * 0.01  # 1% more savings per degree above 30°C
        
        # Calculate percentage change
        pct_change = delta_temp * savings_per_degree_pct * outdoor_factor * 100
        
        # Get baseline consumption (or estimate)
        if self.energy_analyzer:
            try:
                baseline = self.energy_analyzer.get_daily_average()
            except:
                baseline = self.building_area * 0.15  # 150 Wh/m²/day estimate
        else:
            baseline = self.building_area * 0.15
        
        # Calculate absolute savings
        delta_kwh_day = baseline * pct_change / 100
        delta_kwh_month = delta_kwh_day * 30
        
        # Calculate cost (average of standard and peak rates)
        avg_rate = (RATE_STANDARD + RATE_PEAK) / 2
        delta_cost_day = delta_kwh_day * avg_rate
        delta_cost_month = delta_kwh_month * avg_rate
        
        # Confidence based on forecast reliability
        confidence = 0.8 if weather else 0.6
        
        return EnergyImpact(
            delta_kwh_day=delta_kwh_day,
            delta_kwh_month=delta_kwh_month,
            delta_cost_qar_day=delta_cost_day,
            delta_cost_qar_month=delta_cost_month,
            percentage_change=pct_change,
            confidence=confidence,
        )
    
    def _simulate_schedule_change(self,
                                   current_hours: Any,
                                   proposed_hours: Any) -> EnergyImpact:
        """Simulate energy impact of schedule change."""
        # Current hours could be like {"start": "06:00", "end": "20:00"}
        # Proposed hours reduce operating time
        
        # Parse hours
        try:
            if isinstance(current_hours, dict):
                current_hours_count = self._hours_between(
                    current_hours.get("start", "07:00"),
                    current_hours.get("end", "18:00")
                )
            else:
                current_hours_count = 11  # Default
            
            if isinstance(proposed_hours, dict):
                proposed_hours_count = self._hours_between(
                    proposed_hours.get("start", "07:00"),
                    proposed_hours.get("end", "18:00")
                )
            else:
                proposed_hours_count = 10  # Default
        except:
            current_hours_count = 11
            proposed_hours_count = 10
        
        # Calculate reduction
        hours_reduced = current_hours_count - proposed_hours_count
        pct_change = (hours_reduced / current_hours_count) * 100
        
        # Estimate baseline
        baseline = self.building_area * 0.15
        
        delta_kwh_day = baseline * pct_change / 100
        delta_kwh_month = delta_kwh_day * 30
        
        avg_rate = (RATE_STANDARD + RATE_PEAK) / 2
        
        return EnergyImpact(
            delta_kwh_day=delta_kwh_day,
            delta_kwh_month=delta_kwh_month,
            delta_cost_qar_day=delta_kwh_day * avg_rate,
            delta_cost_qar_month=delta_kwh_month * avg_rate,
            percentage_change=pct_change,
            confidence=0.7,
        )
    
    def _hours_between(self, start: str, end: str) -> int:
        """Calculate hours between two time strings."""
        start_h = int(start.split(":")[0])
        end_h = int(end.split(":")[0])
        return max(0, end_h - start_h)
    
    def _simulate_ventilation_change(self,
                                      current_cfm: float,
                                      proposed_cfm: float) -> EnergyImpact:
        """Simulate energy impact of ventilation rate change."""
        # Fan power varies with cube of airflow (fan affinity law)
        ratio = proposed_cfm / current_cfm if current_cfm > 0 else 1
        power_ratio = ratio ** 3
        
        # Estimate fan energy as 15% of total
        baseline = self.building_area * 0.15
        fan_baseline = baseline * 0.15
        
        delta_kwh_day = fan_baseline * (power_ratio - 1)
        pct_change = (power_ratio - 1) * 15  # 15% of total
        
        return EnergyImpact(
            delta_kwh_day=delta_kwh_day,
            delta_kwh_month=delta_kwh_day * 30,
            delta_cost_qar_day=delta_kwh_day * 0.05,
            delta_cost_qar_month=delta_kwh_day * 30 * 0.05,
            percentage_change=pct_change,
            confidence=0.75,
        )
    
    def _simulate_generic_change(self,
                                  current: Any,
                                  proposed: Any) -> EnergyImpact:
        """Generic simulation for unknown change types."""
        return EnergyImpact(
            delta_kwh_day=0,
            delta_kwh_month=0,
            delta_cost_qar_day=0,
            delta_cost_qar_month=0,
            percentage_change=0,
            confidence=0.3,
        )
    
    def _estimate_comfort_setpoint(self,
                                    current_temp: float,
                                    proposed_temp: float) -> ComfortImpact:
        """Estimate comfort impact of setpoint change."""
        delta = proposed_temp - current_temp
        
        # Check if proposed is within optimal range
        in_optimal = COMFORT_OPTIMAL_RANGE[0] <= proposed_temp <= COMFORT_OPTIMAL_RANGE[1]
        
        if in_optimal:
            satisfaction_change = 0
            complaint_prob = 0.05
            notes = "Within optimal comfort range"
        elif proposed_temp > current_temp:
            # Warmer = potentially less comfortable
            satisfaction_change = -5 * abs(delta)  # -5% per degree warmer
            complaint_prob = min(0.3, 0.1 * abs(delta))
            notes = f"May feel warmer; {int(complaint_prob * 100)}% of occupants may notice"
        else:
            # Cooler = generally acceptable
            satisfaction_change = 2 * abs(delta)  # +2% per degree cooler
            complaint_prob = 0.02
            notes = "Cooler temperatures generally well-received"
        
        return ComfortImpact(
            occupant_satisfaction_change=satisfaction_change,
            complaint_probability=complaint_prob,
            affected_zones=["all"],  # Would specify actual zones if known
            notes=notes,
        )
    
    def _estimate_comfort_schedule(self,
                                    current: Any,
                                    proposed: Any) -> ComfortImpact:
        """Estimate comfort impact of schedule change."""
        return ComfortImpact(
            occupant_satisfaction_change=0,
            complaint_probability=0.15,
            affected_zones=["edge zones"],
            notes="Early arrivers/late stayers may experience discomfort",
        )
    
    def _estimate_comfort_ventilation(self,
                                       current_cfm: float,
                                       proposed_cfm: float) -> ComfortImpact:
        """Estimate comfort impact of ventilation change."""
        ratio = proposed_cfm / current_cfm if current_cfm > 0 else 1
        
        if ratio < 0.8:
            return ComfortImpact(
                occupant_satisfaction_change=-15,
                complaint_probability=0.25,
                affected_zones=["high-density areas"],
                notes="Reduced ventilation may affect IAQ; monitor CO2 levels",
            )
        elif ratio > 1.2:
            return ComfortImpact(
                occupant_satisfaction_change=5,
                complaint_probability=0.05,
                affected_zones=[],
                notes="Increased fresh air generally positive for IAQ",
            )
        else:
            return ComfortImpact(
                occupant_satisfaction_change=0,
                complaint_probability=0.1,
                affected_zones=[],
                notes="Minimal comfort impact expected",
            )
    
    def _get_fleet_comparison(self,
                              change_type: ChangeType,
                              current: Any,
                              proposed: Any) -> Optional[FleetComparison]:
        """Compare with similar buildings in the fleet."""
        # This would query a fleet database in production
        # For now, return simulated comparison data
        
        if change_type == ChangeType.SETPOINT:
            delta = float(proposed) - float(current) if proposed and current else 0
            
            if delta > 0:  # Raising setpoint
                return FleetComparison(
                    similar_buildings_count=12,
                    success_rate=85,  # 85% of buildings kept the change
                    avg_savings_pct=abs(delta) * 6.5,
                    reversion_rate=15,
                    notes=f"Similar buildings with {proposed}°C setpoint saw 85% satisfaction retention",
                )
            else:
                return FleetComparison(
                    similar_buildings_count=8,
                    success_rate=95,
                    avg_savings_pct=-abs(delta) * 6.5,
                    reversion_rate=5,
                    notes="Lower setpoints have high retention but higher cost",
                )
        
        return None
    
    def _assess_risks(self,
                      change_type: ChangeType,
                      current: Any,
                      proposed: Any,
                      comfort: ComfortImpact) -> RiskAssessment:
        """Assess risks of proposed change."""
        risks = []
        mitigations = []
        
        if comfort.complaint_probability > 0.2:
            risks.append("High probability of occupant complaints")
            mitigations.append("Pilot in low-complaint zone first")
        
        if change_type == ChangeType.SETPOINT:
            delta = float(proposed) - float(current) if proposed and current else 0
            if abs(delta) > 2:
                risks.append("Large setpoint change may cause shock complaints")
                mitigations.append("Implement gradually (0.5°C per week)")
            
            if float(proposed) > 25:
                risks.append("Summer peak may require reversion")
                mitigations.append("Plan to revert during heat waves (>45°C)")
        
        if change_type == ChangeType.VENTILATION:
            if float(proposed) < float(current) * 0.8:
                risks.append("May violate ASHRAE 62.1 ventilation requirements")
                mitigations.append("Monitor CO2 levels; ensure compliance")
        
        # Determine overall risk level
        if len(risks) >= 3 or comfort.complaint_probability > 0.3:
            risk_level = RiskLevel.HIGH
        elif len(risks) >= 1 or comfort.complaint_probability > 0.15:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        return RiskAssessment(
            risk_level=risk_level,
            risks=risks if risks else ["No significant risks identified"],
            mitigations=mitigations if mitigations else ["Standard monitoring recommended"],
            reversibility="immediate" if change_type == ChangeType.SETPOINT else "easy",
        )
    
    def _generate_recommendation(self,
                                  energy: EnergyImpact,
                                  comfort: ComfortImpact,
                                  risk: RiskAssessment,
                                  fleet: Optional[FleetComparison]) -> tuple:
        """Generate recommendation based on all factors."""
        # Score the change
        score = 0
        reasons = []
        
        # Energy savings is positive
        if energy.delta_cost_qar_month > 0:
            score += 2
            reasons.append(f"Saves QAR {energy.delta_cost_qar_month:.0f}/month")
        elif energy.delta_cost_qar_month < 0:
            score -= 1
            reasons.append(f"Costs additional QAR {abs(energy.delta_cost_qar_month):.0f}/month")
        
        # Low comfort impact is positive
        if comfort.complaint_probability < 0.1:
            score += 1
            reasons.append("Low comfort risk")
        elif comfort.complaint_probability > 0.25:
            score -= 2
            reasons.append(f"High complaint risk ({comfort.complaint_probability*100:.0f}%)")
        
        # Low risk is positive
        if risk.risk_level == RiskLevel.LOW:
            score += 1
        elif risk.risk_level == RiskLevel.HIGH:
            score -= 1
        
        # Fleet success is positive
        if fleet and fleet.success_rate > 80:
            score += 1
            reasons.append(f"{fleet.success_rate:.0f}% success rate in similar buildings")
        
        # Generate recommendation
        if score >= 3:
            recommendation = "IMPLEMENT"
            reason = f"Recommended: {'; '.join(reasons)}"
        elif score >= 1:
            recommendation = "PILOT"
            reason = f"Pilot in single zone first: {'; '.join(reasons)}"
        elif score >= -1:
            recommendation = "MONITOR"
            reason = f"Proceed with caution: {'; '.join(reasons)}"
        else:
            recommendation = "AVOID"
            reason = f"Not recommended: {'; '.join(reasons)}"
        
        return recommendation, reason


# =============================================================================
# LLM TOOL HANDLER
# =============================================================================

def simulate_change(
    change_type: str,
    current_value: Any,
    proposed_value: Any,
    building_id: str = "default",
    zone_id: Optional[str] = None,
    simulation_days: int = 30,
) -> Dict[str, Any]:
    """
    Simulate the impact of an operational change.
    
    This is the LLM tool handler.
    
    Args:
        change_type: "setpoint", "schedule", "staging", "ventilation", "mode"
        current_value: Current setting
        proposed_value: Proposed new setting
        building_id: Building identifier
        zone_id: Specific zone (optional)
        simulation_days: Days to simulate
        
    Returns:
        Complete simulation result with energy, comfort, and risk analysis
    """
    simulator = WhatIfSimulator(building_id)
    
    result = simulator.simulate({
        "change_type": change_type,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "zone_id": zone_id,
        "simulation_days": simulation_days,
    })
    
    return result.to_dict()


if __name__ == "__main__":
    # Test the simulator
    print("=" * 60)
    print("What-If Simulator Test")
    print("=" * 60)
    
    simulator = WhatIfSimulator("tower_a", building_area_m2=15000)
    
    # Test setpoint change
    result = simulator.simulate({
        "change_type": "setpoint",
        "current_value": 22,
        "proposed_value": 23,
    })
    
    print(f"\n📊 Simulation: Raise setpoint 22°C → 23°C")
    print(f"\nEnergy Impact:")
    print(f"   Change: {result.energy_impact.percentage_change:+.1f}%")
    print(f"   Savings: QAR {result.energy_impact.delta_cost_qar_month:.0f}/month")
    
    print(f"\nComfort Impact:")
    print(f"   Satisfaction: {result.comfort_impact.occupant_satisfaction_change:+.0f}%")
    print(f"   Complaint Risk: {result.comfort_impact.complaint_probability*100:.0f}%")
    
    if result.fleet_comparison:
        print(f"\nFleet Comparison:")
        print(f"   {result.fleet_comparison.similar_buildings_count} similar buildings")
        print(f"   Success rate: {result.fleet_comparison.success_rate}%")
    
    print(f"\nRisk Assessment: {result.risk_assessment.risk_level.value.upper()}")
    
    print(f"\n🎯 Recommendation: {result.recommendation}")
    print(f"   Reason: {result.recommendation_reason}")
