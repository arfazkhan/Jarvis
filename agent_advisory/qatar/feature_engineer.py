"""
Qatar Feature Engineering
===========================

Extract 50+ features for ML models from building context.
All features are numeric/categorical for ML consumption.

Features are LEARNED correlations - models discover what matters.
"""

import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
import math

from .context import (
    is_qatar_working_day,
    is_ramadan,
    is_summer,
    is_sandstorm_season,
    minutes_to_next_prayer,
    get_kahramaa_rate,
    get_building_profile,
    QATAR_CALENDAR,
)


class QatarFeatureEngineer:
    """
    Extract Qatar-specific features for ML models.
    
    All features are numeric for XGBoost/LightGBM consumption.
    Categorical features are one-hot or label encoded.
    
    Feature Groups:
    - Temporal (8 features)
    - Environmental (12 features)
    - Building State (15 features)
    - Equipment (10 features)
    - Historical (5 features)
    
    Total: 50 features
    """
    
    FEATURE_NAMES = [
        # Temporal (8)
        "hour_sin", "hour_cos", "day_of_week", "is_weekend",
        "is_ramadan", "is_summer", "prayer_time_proximity_min",
        "days_to_major_event",
        
        # Environmental (12)
        "outdoor_temp_c", "outdoor_humidity_pct", "solar_radiation_wm2",
        "wind_speed_ms", "sandstorm_probability", "dew_point_c",
        "feels_like_temp_c", "cooling_degree_hours", "humidity_ratio",
        "wet_bulb_temp_c", "is_extreme_heat", "is_sandstorm_active",
        
        # Building State (15)
        "zone_temp_avg_c", "zone_temp_variance", "supply_air_temp_c",
        "return_air_temp_c", "chw_supply_temp_c", "chw_delta_t_c",
        "ahu_static_pressure_pa", "vav_position_avg_pct",
        "occupancy_ratio", "cooling_load_pct", "chiller_efficiency_kw_ton",
        "total_power_kw", "lighting_power_pct", "plug_load_pct",
        "fresh_air_ratio_pct",
        
        # Equipment (10)
        "equipment_age_years", "hours_since_maintenance",
        "fault_count_30d", "mtbf_hours", "current_alarm_count",
        "similar_equipment_faulted", "redundancy_available",
        "criticality_score", "reliability_score", "parts_availability",
        
        # Historical (5)
        "similar_scenario_outcome_avg", "operator_preference_score",
        "action_success_rate_30d", "time_to_resolution_avg_min",
        "cost_per_resolution_avg_qar",
    ]
    
    def __init__(self):
        self.feature_count = len(self.FEATURE_NAMES)
    
    def extract_features(
        self,
        context: Dict[str, Any],
        action: Optional[Dict[str, Any]] = None
    ) -> np.ndarray:
        """
        Extract all features from context.
        
        Args:
            context: Current operational context
            action: Optional action being evaluated
            
        Returns:
            numpy array of shape (50,) with all features
        """
        features = []
        
        # Get timestamp
        timestamp = context.get("timestamp", datetime.now())
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        elif isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp)
        
        # ─────────────────────────────────────────────────────────────────
        # TEMPORAL FEATURES (8)
        # ─────────────────────────────────────────────────────────────────
        
        # Cyclical hour encoding
        hour = timestamp.hour + timestamp.minute / 60
        features.append(math.sin(2 * math.pi * hour / 24))  # hour_sin
        features.append(math.cos(2 * math.pi * hour / 24))  # hour_cos
        
        # Day of week (0-6, Qatar: Sunday=0)
        qatar_dow = (timestamp.weekday() + 1) % 7  # Shift to make Sunday=0
        features.append(qatar_dow)  # day_of_week
        
        # Weekend flag
        features.append(1.0 if qatar_dow in [5, 6] else 0.0)  # is_weekend (Fri, Sat)
        
        # Ramadan flag
        features.append(1.0 if is_ramadan(timestamp) else 0.0)  # is_ramadan
        
        # Summer flag
        features.append(1.0 if is_summer(timestamp) else 0.0)  # is_summer
        
        # Prayer time proximity
        features.append(minutes_to_next_prayer(timestamp))  # prayer_time_proximity_min
        
        # Days to major event (default 30 if unknown)
        features.append(context.get("days_to_major_event", 30))  # days_to_major_event
        
        # ─────────────────────────────────────────────────────────────────
        # ENVIRONMENTAL FEATURES (12)
        # ─────────────────────────────────────────────────────────────────
        
        outdoor_temp = context.get("outdoor_temp_c", 35.0)
        outdoor_humidity = context.get("outdoor_humidity_pct", 50.0)
        
        features.append(outdoor_temp)  # outdoor_temp_c
        features.append(outdoor_humidity)  # outdoor_humidity_pct
        
        # Solar radiation (estimate from time if not provided)
        if "solar_radiation_wm2" in context:
            features.append(context["solar_radiation_wm2"])
        else:
            # Estimate based on hour and season
            if 6 <= timestamp.hour <= 18:
                base_solar = 800 if is_summer(timestamp) else 600
                hour_factor = 1 - abs(timestamp.hour - 12) / 6
                features.append(base_solar * hour_factor)
            else:
                features.append(0.0)
        
        features.append(context.get("wind_speed_ms", 3.0))  # wind_speed_ms
        
        # Sandstorm probability
        if is_sandstorm_season(timestamp):
            features.append(QATAR_CALENDAR["sandstorm_probability_high"])
        else:
            features.append(QATAR_CALENDAR["sandstorm_probability_low"])
        
        # Dew point (calculated)
        dew_point = self._calculate_dew_point(outdoor_temp, outdoor_humidity)
        features.append(dew_point)  # dew_point_c
        
        # Feels like temperature (heat index for hot/humid)
        feels_like = self._calculate_heat_index(outdoor_temp, outdoor_humidity)
        features.append(feels_like)  # feels_like_temp_c
        
        # Cooling degree hours (for the day)
        features.append(context.get("cooling_degree_hours", (outdoor_temp - 24) * 24))
        
        # Humidity ratio
        humidity_ratio = self._calculate_humidity_ratio(outdoor_temp, outdoor_humidity)
        features.append(humidity_ratio)  # humidity_ratio
        
        # Wet bulb temperature
        wet_bulb = self._calculate_wet_bulb(outdoor_temp, outdoor_humidity)
        features.append(wet_bulb)  # wet_bulb_temp_c
        
        # Extreme heat flag
        features.append(1.0 if outdoor_temp >= 45 else 0.0)  # is_extreme_heat
        
        # Sandstorm active flag
        features.append(1.0 if context.get("sandstorm_active", False) else 0.0)
        
        # ─────────────────────────────────────────────────────────────────
        # BUILDING STATE FEATURES (15)
        # ─────────────────────────────────────────────────────────────────
        
        features.append(context.get("zone_temp_avg_c", 23.0))  # zone_temp_avg_c
        features.append(context.get("zone_temp_variance", 0.5))  # zone_temp_variance
        features.append(context.get("supply_air_temp_c", 13.0))  # supply_air_temp_c
        features.append(context.get("return_air_temp_c", 24.0))  # return_air_temp_c
        features.append(context.get("chw_supply_temp_c", 6.5))  # chw_supply_temp_c
        features.append(context.get("chw_delta_t_c", 5.5))  # chw_delta_t_c
        features.append(context.get("ahu_static_pressure_pa", 250))  # ahu_static_pressure_pa
        features.append(context.get("vav_position_avg_pct", 65))  # vav_position_avg_pct
        features.append(context.get("occupancy_ratio", 0.7))  # occupancy_ratio
        features.append(context.get("cooling_load_pct", 75))  # cooling_load_pct
        features.append(context.get("chiller_efficiency_kw_ton", 0.65))  # chiller_efficiency_kw_ton
        features.append(context.get("total_power_kw", 500))  # total_power_kw
        features.append(context.get("lighting_power_pct", 30))  # lighting_power_pct
        features.append(context.get("plug_load_pct", 25))  # plug_load_pct
        features.append(context.get("fresh_air_ratio_pct", 20))  # fresh_air_ratio_pct
        
        # ─────────────────────────────────────────────────────────────────
        # EQUIPMENT FEATURES (10)
        # ─────────────────────────────────────────────────────────────────
        
        features.append(context.get("equipment_age_years", 5))  # equipment_age_years
        features.append(context.get("hours_since_maintenance", 720))  # hours_since_maintenance
        features.append(context.get("fault_count_30d", 2))  # fault_count_30d
        features.append(context.get("mtbf_hours", 2000))  # mtbf_hours
        features.append(context.get("current_alarm_count", 1))  # current_alarm_count
        features.append(1.0 if context.get("similar_equipment_faulted", False) else 0.0)
        features.append(1.0 if context.get("redundancy_available", True) else 0.0)
        features.append(context.get("criticality_score", 3) / 5.0)  # Normalize to 0-1
        features.append(context.get("reliability_score", 0.85))  # reliability_score
        features.append(context.get("parts_availability", 0.9))  # parts_availability
        
        # ─────────────────────────────────────────────────────────────────
        # HISTORICAL FEATURES (5)
        # ─────────────────────────────────────────────────────────────────
        
        features.append(context.get("similar_scenario_outcome_avg", 0.7))
        features.append(context.get("operator_preference_score", 0.5))
        features.append(context.get("action_success_rate_30d", 0.8))
        features.append(context.get("time_to_resolution_avg_min", 45))
        features.append(context.get("cost_per_resolution_avg_qar", 500))
        
        return np.array(features, dtype=np.float32)
    
    def extract_features_batch(
        self,
        contexts: List[Dict[str, Any]]
    ) -> np.ndarray:
        """Extract features for multiple contexts"""
        return np.array([self.extract_features(c) for c in contexts])
    
    def get_feature_names(self) -> List[str]:
        """Get ordered list of feature names"""
        return self.FEATURE_NAMES.copy()
    
    def _calculate_dew_point(self, temp_c: float, humidity_pct: float) -> float:
        """Calculate dew point temperature"""
        a = 17.27
        b = 237.7
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100)
        return (b * alpha) / (a - alpha)
    
    def _calculate_heat_index(self, temp_c: float, humidity_pct: float) -> float:
        """Calculate heat index (feels-like temperature)"""
        # Convert to Fahrenheit for standard formula
        temp_f = temp_c * 9/5 + 32
        
        if temp_f < 80:
            return temp_c
        
        # Rothfusz regression
        hi = (-42.379 + 2.04901523 * temp_f + 10.14333127 * humidity_pct
              - 0.22475541 * temp_f * humidity_pct
              - 0.00683783 * temp_f**2 - 0.05481717 * humidity_pct**2
              + 0.00122874 * temp_f**2 * humidity_pct
              + 0.00085282 * temp_f * humidity_pct**2
              - 0.00000199 * temp_f**2 * humidity_pct**2)
        
        # Convert back to Celsius
        return (hi - 32) * 5/9
    
    def _calculate_humidity_ratio(self, temp_c: float, humidity_pct: float) -> float:
        """Calculate humidity ratio (kg water / kg dry air)"""
        # Saturation pressure (simplified)
        psat = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        pv = (humidity_pct / 100) * psat
        patm = 101.325  # kPa
        return 0.622 * pv / (patm - pv)
    
    def _calculate_wet_bulb(self, temp_c: float, humidity_pct: float) -> float:
        """Approximate wet bulb temperature"""
        # Stull formula (2011)
        t = temp_c
        rh = humidity_pct
        
        tw = (t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
              + math.atan(t + rh) - math.atan(rh - 1.676331)
              + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
              - 4.686035)
        
        return tw


class ActionFeatureEngineer:
    """
    Extract features from action options for ranking.
    
    Used by the preference ranking model.
    """
    
    ACTION_FEATURE_NAMES = [
        "action_type_encoded",
        "intensity_level",
        "estimated_cost_qar",
        "estimated_time_min",
        "risk_score",
        "comfort_impact",
        "energy_impact_pct",
        "gsas_impact",
        "requires_shutdown",
        "requires_operator_presence",
        "is_reversible",
        "equipment_count",
    ]
    
    ACTION_TYPE_ENCODING = {
        "shutdown": 0,
        "reduce_load": 1,
        "stage_down": 2,
        "setpoint_adjust": 3,
        "schedule_maintenance": 4,
        "investigate": 5,
        "recirculation_mode": 6,
        "bypass_filter": 7,
        "switch_equipment": 8,
        "do_nothing": 9,
        "other": 10,
    }
    
    def extract_features(self, action: Dict[str, Any]) -> np.ndarray:
        """Extract features from action option"""
        features = []
        
        # Action type (encoded)
        action_type = action.get("action_type", action.get("action", "other"))
        features.append(self.ACTION_TYPE_ENCODING.get(action_type, 10))
        
        # Intensity (0-1)
        features.append(action.get("intensity", 0.5))
        
        # Cost
        features.append(action.get("estimated_cost_qar", 0))
        
        # Time
        features.append(action.get("estimated_time_min", 30))
        
        # Risk (1-5)
        features.append(action.get("risk_score", 3))
        
        # Comfort impact (-1 to 1)
        features.append(action.get("comfort_impact", 0))
        
        # Energy impact (%)
        features.append(action.get("energy_impact_pct", 0))
        
        # GSAS impact
        features.append(action.get("gsas_impact", 0))
        
        # Binary flags
        features.append(1.0 if action.get("requires_shutdown", False) else 0.0)
        features.append(1.0 if action.get("requires_operator_presence", True) else 0.0)
        features.append(1.0 if action.get("is_reversible", True) else 0.0)
        
        # Equipment count
        features.append(action.get("equipment_count", 1))
        
        return np.array(features, dtype=np.float32)
    
    def get_feature_names(self) -> List[str]:
        """Get ordered list of feature names"""
        return self.ACTION_FEATURE_NAMES.copy()
