"""
Qatar Module
=============

Qatar/GCC-specific data and feature engineering for ML models.
"""

from .context import (
    # Tariffs
    KAHRAMAA_TARIFFS,
    
    # Calendar
    QATAR_CALENDAR,
    PRAYER_TIMES_SUMMER,
    PRAYER_TIMES_WINTER,
    
    # GSAS
    GSASRating,
    GSAS_BENCHMARKS,
    
    # Buildings
    BuildingProfile,
    QATAR_BUILDINGS,
    
    # Operators
    OperatorPersona,
    OPERATOR_PERSONAS,
    
    # Helpers
    is_qatar_working_day,
    is_ramadan,
    is_summer,
    is_sandstorm_season,
    get_kahramaa_rate,
    get_prayer_times,
    minutes_to_next_prayer,
    calculate_cooling_degree_hours,
    get_building_profile,
    get_operator_persona,
)

from .feature_engineer import (
    QatarFeatureEngineer,
    ActionFeatureEngineer,
)

from .simulator import (
    QatarBuildingSimulator,
    SimulatedScenario,
)

__all__ = [
    # Tariffs
    "KAHRAMAA_TARIFFS",
    
    # Calendar
    "QATAR_CALENDAR",
    "PRAYER_TIMES_SUMMER",
    "PRAYER_TIMES_WINTER",
    
    # GSAS
    "GSASRating",
    "GSAS_BENCHMARKS",
    
    # Buildings
    "BuildingProfile",
    "QATAR_BUILDINGS",
    
    # Operators
    "OperatorPersona",
    "OPERATOR_PERSONAS",
    
    # Helpers
    "is_qatar_working_day",
    "is_ramadan",
    "is_summer",
    "is_sandstorm_season",
    "get_kahramaa_rate",
    "get_prayer_times",
    "minutes_to_next_prayer",
    "calculate_cooling_degree_hours",
    "get_building_profile",
    "get_operator_persona",
    
    # Feature Engineering
    "QatarFeatureEngineer",
    "ActionFeatureEngineer",
    
    # Simulator
    "QatarBuildingSimulator",
    "SimulatedScenario",
]

