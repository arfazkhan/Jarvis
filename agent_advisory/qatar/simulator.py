"""
Qatar Building Simulator
=========================

Generate realistic synthetic data for Qatar/GCC buildings.
Used for training and testing when real data is not available.

Includes:
- Seasonal weather patterns
- Building operational scenarios
- Operator decision simulation
- Outcome simulation
"""

import random
import math
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from .context import (
    QATAR_BUILDINGS,
    OPERATOR_PERSONAS,
    BuildingProfile,
    OperatorPersona,
    is_summer,
    is_ramadan,
    is_sandstorm_season,
    get_kahramaa_rate,
)


@dataclass
class SimulatedScenario:
    """A simulated operational scenario"""
    scenario_id: str
    timestamp: datetime
    building_id: str
    equipment_id: str
    issue_type: str
    
    # Context
    context: Dict[str, Any]
    
    # Ground truth (for training)
    best_action: str
    best_action_details: Dict[str, Any]
    operator_id: str
    operator_decision: str
    
    # Outcome
    outcome_quality: str
    resolution_time_min: int
    cost_qar: float
    utility_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "timestamp": self.timestamp.isoformat(),
            "building_id": self.building_id,
            "equipment_id": self.equipment_id,
            "issue_type": self.issue_type,
            "context": self.context,
            "best_action": self.best_action,
            "best_action_details": self.best_action_details,
            "operator_id": self.operator_id,
            "operator_decision": self.operator_decision,
            "outcome_quality": self.outcome_quality,
            "resolution_time_min": self.resolution_time_min,
            "cost_qar": self.cost_qar,
            "utility_score": self.utility_score,
        }


class QatarBuildingSimulator:
    """
    Simulate Qatar building operations for synthetic data generation.
    
    Realistic simulation includes:
    - Seasonal patterns (summer heat, sandstorms)
    - Building type variations
    - Operator preference patterns
    - Outcome distributions based on action quality
    """
    
    ISSUE_TYPES = [
        "high_head_pressure",
        "high_chw_temp",
        "low_air_flow",
        "high_zone_temp",
        "filter_clogged",
        "compressor_fault",
        "vfd_fault",
        "high_humidity",
        "condenser_dirty",
        "refrigerant_low",
        "belt_wear",
        "bearing_vibration",
        "control_valve_stuck",
        "sensor_drift",
        "schedule_conflict",
    ]
    
    ACTION_TYPES = [
        "reduce_load",
        "stage_down",
        "stage_up",
        "shutdown",
        "switch_equipment",
        "setpoint_adjust",
        "schedule_maintenance",
        "investigate",
        "clean_condenser",
        "replace_filter",
        "add_refrigerant",
        "recirculation_mode",
        "do_nothing",
        "emergency_shutdown",
        "notify_contractor",
    ]
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize simulator.
        
        Args:
            seed: Random seed for reproducibility
        """
        if seed is not None:
            random.seed(seed)
        
        self.buildings = list(QATAR_BUILDINGS.values())
        self.operators = list(OPERATOR_PERSONAS.values())
        self.scenario_counter = 0
    
    def simulate_weather(
        self,
        dt: datetime
    ) -> Dict[str, Any]:
        """
        Simulate Qatar weather for a given datetime.
        
        Returns realistic temperature, humidity, solar patterns.
        """
        # Base temperatures by season
        if is_summer(dt):
            # Summer (May-Sept): 35-48°C
            base_temp = 42
            temp_range = 6
            base_humidity = 45
        else:
            # Winter (Nov-Mar): 15-26°C
            base_temp = 22
            temp_range = 5
            base_humidity = 55
        
        # Diurnal variation
        hour = dt.hour
        diurnal_factor = math.sin((hour - 6) * math.pi / 12)  # Peak at noon
        
        temp = base_temp + temp_range * diurnal_factor + random.gauss(0, 2)
        humidity = base_humidity + random.gauss(0, 10)
        humidity = max(20, min(95, humidity))
        
        # Solar radiation
        if 6 <= hour <= 18:
            solar_base = 800 if is_summer(dt) else 600
            solar = solar_base * max(0, diurnal_factor) + random.gauss(0, 50)
        else:
            solar = 0
        
        # Sandstorm
        sandstorm_active = False
        if is_sandstorm_season(dt):
            if random.random() < 0.05:  # 5% chance during season
                sandstorm_active = True
                humidity = max(20, humidity - 20)
        
        return {
            "outdoor_temp_c": round(temp, 1),
            "outdoor_humidity_pct": round(humidity, 1),
            "solar_radiation_wm2": max(0, round(solar, 0)),
            "wind_speed_ms": round(random.uniform(1, 8), 1),
            "sandstorm_active": sandstorm_active,
        }
    
    def simulate_building_state(
        self,
        building: BuildingProfile,
        weather: Dict[str, Any],
        hour: int
    ) -> Dict[str, Any]:
        """
        Simulate building state based on weather and schedule.
        """
        outdoor_temp = weather["outdoor_temp_c"]
        
        # Occupancy based on hour and building type
        if building.operating_hours == "24/7":
            occupancy = 0.7 + random.uniform(-0.2, 0.2)
        elif 7 <= hour <= 18:
            occupancy = 0.8 + random.uniform(-0.2, 0.2)
        else:
            occupancy = 0.1 + random.uniform(0, 0.1)
        
        # Cooling load correlated with outdoor temp and occupancy
        cooling_load = (
            (outdoor_temp - 24) / 25 * 0.6 +
            occupancy * 0.3 +
            random.uniform(0, 0.1)
        ) * 100
        cooling_load = max(10, min(100, cooling_load))
        
        # Zone temperature (usually controlled)
        zone_temp = 23 + random.gauss(0, 0.5)
        
        # Supply air temp (lower when load is high)
        supply_temp = 13 - (cooling_load / 100) * 2 + random.gauss(0, 0.3)
        
        # Chiller efficiency (degrades with outdoor temp)
        efficiency = 0.55 + random.uniform(0, 0.15)
        if outdoor_temp > 42:
            efficiency += (outdoor_temp - 42) * 0.01  # Less efficient when hot
        
        # Power consumption
        base_power = building.cooling_capacity_tons * 0.8  # kW/ton
        power = base_power * (cooling_load / 100) * efficiency
        
        return {
            "zone_temp_avg_c": round(zone_temp, 1),
            "zone_temp_variance": round(random.uniform(0.2, 1.5), 2),
            "supply_air_temp_c": round(supply_temp, 1),
            "return_air_temp_c": round(zone_temp + random.uniform(0, 1), 1),
            "chw_supply_temp_c": round(6 + random.uniform(-0.5, 0.5), 1),
            "chw_delta_t_c": round(5 + random.uniform(0, 2), 1),
            "ahu_static_pressure_pa": round(250 + random.uniform(-30, 30)),
            "vav_position_avg_pct": round(cooling_load * 0.8 + random.uniform(-10, 10)),
            "occupancy_ratio": round(occupancy, 2),
            "cooling_load_pct": round(cooling_load, 1),
            "chiller_efficiency_kw_ton": round(efficiency, 3),
            "total_power_kw": round(power, 0),
            "lighting_power_pct": round(30 * occupancy, 0),
            "plug_load_pct": round(25 * occupancy, 0),
            "fresh_air_ratio_pct": round(20 + random.uniform(-5, 5), 0),
        }
    
    def simulate_equipment_state(
        self,
        equipment_id: str,
        building: BuildingProfile
    ) -> Dict[str, Any]:
        """Simulate equipment health and status"""
        age = building.hvac_age + random.uniform(-2, 2)
        
        # Reliability decreases with age
        reliability = 0.95 - age * 0.01 + random.uniform(-0.05, 0.05)
        reliability = max(0.6, min(0.99, reliability))
        
        # Maintenance based on age
        hours_since_maint = int(random.expovariate(1/1000))
        
        # Fault likelihood
        fault_count = int(random.expovariate(0.5)) if reliability < 0.85 else 0
        
        return {
            "equipment_id": equipment_id,
            "equipment_age_years": round(age, 1),
            "hours_since_maintenance": hours_since_maint,
            "fault_count_30d": fault_count,
            "mtbf_hours": int(2000 * reliability),
            "current_alarm_count": random.randint(0, 3) if random.random() > reliability else 0,
            "similar_equipment_faulted": random.random() > 0.9,
            "redundancy_available": building.num_chillers > 1,
            "criticality_score": random.randint(2, 5),
            "reliability_score": round(reliability, 2),
            "parts_availability": round(0.8 + random.uniform(0, 0.2), 2),
        }
    
    def simulate_issue(
        self,
        building: BuildingProfile,
        weather: Dict[str, Any],
        building_state: Dict[str, Any]
    ) -> Tuple[str, str]:
        """
        Simulate an operational issue based on conditions.
        
        Returns (issue_type, equipment_id)
        """
        # Higher probability of certain issues in certain conditions
        outdoor_temp = weather["outdoor_temp_c"]
        sandstorm = weather.get("sandstorm_active", False)
        cooling_load = building_state.get("cooling_load_pct", 50)
        
        # Weight issues by conditions
        weights = {issue: 1.0 for issue in self.ISSUE_TYPES}
        
        if outdoor_temp > 42:
            weights["high_head_pressure"] += 3
            weights["condenser_dirty"] += 2
            weights["high_zone_temp"] += 2
        
        if sandstorm:
            weights["filter_clogged"] += 5
            weights["condenser_dirty"] += 3
        
        if cooling_load > 85:
            weights["high_head_pressure"] += 2
            weights["compressor_fault"] += 1
        
        # Select issue
        total = sum(weights.values())
        r = random.uniform(0, total)
        cumulative = 0
        selected_issue = self.ISSUE_TYPES[0]
        
        for issue, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                selected_issue = issue
                break
        
        # Select equipment
        equipment_prefix = "CH" if "chiller" in selected_issue or "head" in selected_issue else "AHU"
        equipment_num = random.randint(1, min(4, building.num_chillers or 3))
        equipment_id = f"{equipment_prefix}-{equipment_num:02d}"
        
        return selected_issue, equipment_id
    
    def simulate_operator_decision(
        self,
        operator: OperatorPersona,
        issue_type: str,
        available_actions: List[Dict[str, Any]]
    ) -> Tuple[int, str]:
        """
        Simulate which option an operator would choose.
        
        Returns (chosen_index, action_type)
        """
        if not available_actions:
            return 0, "do_nothing"
        
        # Score each action using operator preferences
        scores = []
        for action in available_actions:
            score = operator.preference_score(action)
            # Add noise to simulate human variability
            score += random.gauss(0, 0.1)
            scores.append(score)
        
        # Softmax selection (usually pick highest, sometimes explore)
        if random.random() < 0.1:  # 10% random exploration
            chosen_idx = random.randint(0, len(available_actions) - 1)
        else:
            chosen_idx = scores.index(max(scores))
        
        return chosen_idx, available_actions[chosen_idx].get("action_type", "unknown")
    
    def simulate_outcome(
        self,
        issue_type: str,
        action_type: str,
        context: Dict[str, Any]
    ) -> Tuple[str, int, float]:
        """
        Simulate outcome of an action.
        
        Returns (outcome_quality, resolution_time_min, cost_qar)
        """
        # Action-issue compatibility scores (learned from data in production)
        good_matches = {
            "high_head_pressure": ["reduce_load", "stage_down", "clean_condenser"],
            "high_chw_temp": ["reduce_load", "setpoint_adjust"],
            "filter_clogged": ["replace_filter", "recirculation_mode"],
            "high_zone_temp": ["setpoint_adjust", "stage_up"],
            "compressor_fault": ["switch_equipment", "shutdown", "notify_contractor"],
        }
        
        is_good_match = action_type in good_matches.get(issue_type, [])
        
        # Base outcome probabilities
        if is_good_match:
            probs = [0.05, 0.15, 0.40, 0.40]  # [poor, acceptable, good, excellent]
        elif action_type in ["investigate", "schedule_maintenance"]:
            probs = [0.10, 0.30, 0.45, 0.15]
        elif action_type in ["shutdown", "emergency_shutdown"]:
            probs = [0.05, 0.25, 0.60, 0.10]  # Safe but not optimal for energy
        elif action_type == "do_nothing":
            probs = [0.30, 0.35, 0.25, 0.10]
        else:
            probs = [0.15, 0.30, 0.35, 0.20]
        
        # Add context effects
        outdoor_temp = context.get("outdoor_temp_c", 35)
        if outdoor_temp > 45:
            # Extreme heat makes actions harder
            probs[0] += 0.1
            probs[3] -= 0.1
        
        # Normalize and select
        total = sum(probs)
        probs = [p / total for p in probs]
        
        qualities = ["poor", "acceptable", "good", "excellent"]
        outcome = random.choices(qualities, weights=probs)[0]
        
        # Resolution time
        base_time = {
            "shutdown": 5,
            "emergency_shutdown": 2,
            "setpoint_adjust": 10,
            "reduce_load": 15,
            "stage_down": 20,
            "switch_equipment": 30,
            "investigate": 60,
            "schedule_maintenance": 1440,
            "replace_filter": 45,
            "clean_condenser": 120,
            "notify_contractor": 240,
        }.get(action_type, 30)
        
        resolution_time = int(base_time * (1 + random.uniform(-0.3, 0.5)))
        
        # Cost (KAHRAMAA + labor)
        energy_cost = base_time * 5 * get_kahramaa_rate("commercial_office")
        labor_cost = base_time * 0.5  # QAR/min labor
        cost = energy_cost + labor_cost + random.uniform(0, 200)
        
        return outcome, resolution_time, round(cost, 2)

    def calculate_utility(
        self,
        outcome_quality: str,
        resolution_time_min: int,
        cost_qar: float,
        action_type: str
    ) -> float:
        """
        Calculate continuous utility score (0.0 to 1.0).
        
        Formula: U = w1*Outcome + w2*Time + w3*Cost + w4*Comfort
        """
        # Base utility from outcome quality (Feasibility)
        base_scores = {
            "excellent": 1.0,
            "good": 0.8,
            "acceptable": 0.5,
            "poor": 0.2
        }
        score = base_scores.get(outcome_quality, 0.5)
        
        # Penalize time (Logarithmic penalty for long times)
        # 30 mins = -0.05, 4 hours = -0.2, 24 hours = -0.4
        time_penalty = 0.0
        if resolution_time_min > 30:
            time_penalty = math.log10(resolution_time_min / 30) * 0.15
        score -= min(0.4, time_penalty)
        
        # Penalize cost
        # 100 QAR = -0.02, 1000 QAR = -0.1
        cost_penalty = min(0.3, cost_qar / 5000)
        score -= cost_penalty
        
        # Bonus for comfort preservation (action-specific)
        comfort_bonus = 0.0
        if action_type in ["setpoint_adjust", "replace_filter", "clean_condenser"]:
            comfort_bonus = 0.1
        elif action_type in ["shutdown", "do_nothing"]:
            comfort_bonus = -0.1
        score += comfort_bonus
        
        return max(0.0, min(1.0, round(score, 4)))
    
    def generate_scenario(
        self,
        dt: Optional[datetime] = None,
        building: Optional[BuildingProfile] = None,
        operator: Optional[OperatorPersona] = None
    ) -> SimulatedScenario:
        """
        Generate a complete simulated scenario.
        
        Returns a SimulatedScenario with all components.
        """
        # Defaults
        if dt is None:
            # Random datetime in last year
            days_back = random.randint(1, 365)
            hours = random.randint(0, 23)
            dt = datetime.now() - timedelta(days=days_back, hours=hours)
        
        if building is None:
            building = random.choice(self.buildings)
        
        if operator is None:
            operator = random.choice(self.operators)
        
        # Generate context
        weather = self.simulate_weather(dt)
        building_state = self.simulate_building_state(building, weather, dt.hour)
        
        # Generate issue
        issue_type, equipment_id = self.simulate_issue(
            building, weather, building_state
        )
        
        equipment_state = self.simulate_equipment_state(equipment_id, building)
        
        # Full context
        context = {
            "timestamp": dt.isoformat(),
            **weather,
            **building_state,
            **equipment_state,
            "building_id": building.id,
            "is_ramadan": is_ramadan(dt),
            "is_summer": is_summer(dt),
        }
        
        # Generate action options
        actions = self._generate_action_options(issue_type, equipment_id)
        
        # Simulate operator decision
        chosen_idx, chosen_action = self.simulate_operator_decision(
            operator, issue_type, actions
        )
        
        chosen_action_details = actions[chosen_idx] if chosen_idx < len(actions) else {}
        
        # Simulate outcome
        outcome_quality, resolution_time, cost = self.simulate_outcome(
            issue_type, chosen_action, context
        )
        
        # Calculate continuous utility score
        utility_score = self.calculate_utility(
            outcome_quality=outcome_quality,
            resolution_time_min=resolution_time,
            cost_qar=cost,
            action_type=chosen_action
        )
        
        # Best action (ground truth - what would have been optimal)
        best_action = self._determine_best_action(issue_type, context)
        best_action_details = next(
            (a for a in actions if a.get("action_type") == best_action),
            {}
        )
        
        self.scenario_counter += 1
        
        return SimulatedScenario(
            scenario_id=f"SIM-{self.scenario_counter:06d}",
            timestamp=dt,
            building_id=building.id,
            equipment_id=equipment_id,
            issue_type=issue_type,
            context=context,
            best_action=best_action,
            best_action_details=best_action_details,
            operator_id=operator.id,
            operator_decision=chosen_action,
            outcome_quality=outcome_quality,
            resolution_time_min=resolution_time,
            cost_qar=cost,
            utility_score=utility_score,
        )
    
    def generate_scenarios(
        self,
        n: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[SimulatedScenario]:
        """
        Generate multiple scenarios.
        
        Args:
            n: Number of scenarios to generate
            start_date: Start of date range
            end_date: End of date range
        """
        scenarios = []
        
        start = start_date or (datetime.now() - timedelta(days=365))
        end = end_date or datetime.now()
        
        for _ in range(n):
            # Random datetime in range
            delta = end - start
            random_seconds = random.randint(0, int(delta.total_seconds()))
            dt = start + timedelta(seconds=random_seconds)
            
            scenario = self.generate_scenario(dt=dt)
            scenarios.append(scenario)
        
        return scenarios
    
    def _generate_action_options(
        self,
        issue_type: str,
        equipment_id: str
    ) -> List[Dict[str, Any]]:
        """Generate realistic action options for an issue"""
        options = []
        
        # Common actions for most issues
        base_actions = [
            {
                "action_type": "investigate",
                "action_description": f"Dispatch technician to investigate {equipment_id}",
                "equipment_id": equipment_id,
                "risk_score": 1,
                "comfort_score": 4,
                "energy_impact_pct": 0,
                "estimated_time_min": 60,
                "estimated_cost_qar": 200,
            },
            {
                "action_type": "schedule_maintenance",
                "action_description": f"Schedule preventive maintenance for {equipment_id}",
                "equipment_id": equipment_id,
                "risk_score": 1,
                "comfort_score": 4,
                "energy_impact_pct": 0,
                "estimated_time_min": 1440,
                "estimated_cost_qar": 500,
            },
        ]
        
        # Issue-specific actions
        issue_actions = {
            "high_head_pressure": [
                {
                    "action_type": "reduce_load",
                    "action_description": f"Reduce cooling load on {equipment_id} by 20%",
                    "risk_score": 2,
                    "comfort_score": 3,
                    "energy_impact_pct": -15,
                },
                {
                    "action_type": "stage_down",
                    "action_description": f"Stage down {equipment_id} to partial load",
                    "risk_score": 2,
                    "comfort_score": 3,
                    "energy_impact_pct": -25,
                },
                {
                    "action_type": "clean_condenser",
                    "action_description": f"Emergency condenser cleaning on {equipment_id}",
                    "risk_score": 2,
                    "comfort_score": 4,
                    "energy_impact_pct": -10,
                },
            ],
            "filter_clogged": [
                {
                    "action_type": "replace_filter",
                    "action_description": f"Replace air filters on {equipment_id}",
                    "risk_score": 1,
                    "comfort_score": 5,
                    "energy_impact_pct": -5,
                },
                {
                    "action_type": "recirculation_mode",
                    "action_description": f"Switch {equipment_id} to recirculation mode",
                    "risk_score": 3,
                    "comfort_score": 2,
                    "energy_impact_pct": -20,
                },
            ],
            "high_zone_temp": [
                {
                    "action_type": "setpoint_adjust",
                    "action_description": f"Lower supply air setpoint on {equipment_id}",
                    "risk_score": 1,
                    "comfort_score": 5,
                    "energy_impact_pct": 5,
                },
                {
                    "action_type": "stage_up",
                    "action_description": f"Increase capacity on {equipment_id}",
                    "risk_score": 2,
                    "comfort_score": 5,
                    "energy_impact_pct": 15,
                },
            ],
        }
        
        # Combine
        options.extend(base_actions)
        options.extend(issue_actions.get(issue_type, []))
        
        # Add equipment_id and defaults
        for opt in options:
            opt.setdefault("equipment_id", equipment_id)
            opt.setdefault("risk_score", 3)
            opt.setdefault("comfort_score", 3)
            opt.setdefault("energy_impact_pct", 0)
            opt.setdefault("estimated_time_min", 30)
            opt.setdefault("estimated_cost_qar", 100)
        
        return options[:5]  # Max 5 options
    
    def _determine_best_action(
        self,
        issue_type: str,
        context: Dict[str, Any]
    ) -> str:
        """Determine the optimal action (ground truth for training)"""
        # Simplified optimal action mapping
        # In production, this would be learned from outcomes
        best_actions = {
            "high_head_pressure": "reduce_load",
            "high_chw_temp": "setpoint_adjust",
            "filter_clogged": "replace_filter",
            "high_zone_temp": "setpoint_adjust",
            "compressor_fault": "switch_equipment",
            "condenser_dirty": "clean_condenser",
            "refrigerant_low": "notify_contractor",
            "vfd_fault": "switch_equipment",
        }
        
        return best_actions.get(issue_type, "investigate")
