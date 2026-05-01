"""
ASHRAE HVAC Equipment Default Parameters
==========================================

Sources:
- ASHRAE Handbook 2019 — HVAC Systems and Equipment
- ASHRAE Handbook 2021 — Applications (Maintenance Chapter)
- ASHRAE General Project Committee (GPC) reliability surveys (2016)

Weibull Parameters:
  alpha (scale)  = characteristic life (hours until 63.2% have failed)
  beta  (shape)  = failure mode exponent:
    beta < 1  = infant mortality / early failures
    beta = 1  = random / exponential failures
    beta > 1  = wear-out / fatigue failures  ← most HVAC equipment

MTBF values are runtime-weighted means for commercial applications
in GCC/Qatar climate (high ambient temps, long cooling seasons).

Service intervals are ASHRAE-recommended inspection/replacement cycles.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class EquipmentDefaults:
    """ASHRAE baseline parameters for one equipment family."""
    mtbf_hours: float
    alpha_hours: float           # Weibull characteristic life (hours)
    beta: float                 # Weibull shape parameter
    service_interval_months: int
    runtime_per_year_hours: float
    critical_subcomponents: List[str]


# Equipment type keys MUST match EquipmentType enum .name values in bms_data_model.py
ASHRAE_DEFAULTS: Dict[str, EquipmentDefaults] = {

    "CHILLER": EquipmentDefaults(
        mtbf_hours=50_000,
        alpha_hours=55_000,
        beta=1.4,
        service_interval_months=12,
        runtime_per_year_hours=4_380,
        critical_subcomponents=[
            "compressor",
            "evaporator tubes",
            "condenser tubes",
            "refrigerant charge",
            "lube oil",
            "expansion valve",
        ],
    ),

    "AHU": EquipmentDefaults(
        mtbf_hours=100_000,
        alpha_hours=110_000,
        beta=1.6,
        service_interval_months=6,
        runtime_per_year_hours=8_760,
        critical_subcomponents=[
            "supply fan",
            "return fan",
            "filters",
            "cooling coil",
            "heating coil",
            "drain pan",
            "fan bearings",
            "actuators",
        ],
    ),

    "COOLING_TOWER": EquipmentDefaults(
        mtbf_hours=75_000,
        alpha_hours=82_000,
        beta=1.3,
        service_interval_months=3,
        runtime_per_year_hours=6_570,
        critical_subcomponents=[
            "fan gearbox",
            "drift eliminator",
            "basin",
            "fill media",
            "water treatment system",
            "bleed valve",
        ],
    ),

    "VAV": EquipmentDefaults(
        mtbf_hours=80_000,
        alpha_hours=88_000,
        beta=1.5,
        service_interval_months=24,
        runtime_per_year_hours=8_760,
        critical_subcomponents=[
            "damper actuator",
            "velocity sensor",
            "controller card",
            "heating coil",
            "ductwork connection",
        ],
    ),

    "FCU": EquipmentDefaults(
        mtbf_hours=60_000,
        alpha_hours=66_000,
        beta=1.5,
        service_interval_months=6,
        runtime_per_year_hours=8_760,
        critical_subcomponents=[
            "fan motor",
            "fan blades",
            "cooling coil",
            "heating coil",
            "drain pan",
            "filter",
        ],
    ),

    "PUMP": EquipmentDefaults(
        mtbf_hours=70_000,
        alpha_hours=77_000,
        beta=1.5,
        service_interval_months=12,
        runtime_per_year_hours=8_760,
        critical_subcomponents=[
            "motor bearings",
            "mechanical seal",
            "impeller",
            "coupling",
            "bearing frame",
        ],
    ),
}


# ─── Normalize key → canonical ASHRAE key ───────────────────────────────────

_EQUIPMENT_TYPE_MAP = {
    # lowercase + underscore variants map to canonical key
    "chiller": "CHILLER",
    "air_handling_unit": "AHU",
    "ahu": "AHU",
    "air handling unit": "AHU",
    "cooling_tower": "COOLING_TOWER",
    "cooling tower": "COOLING_TOWER",
    "variable_air_volume": "VAV",
    "vav": "VAV",
    "variable air volume": "VAV",
    "fan_coil_unit": "FCU",
    "fcu": "FCU",
    "fan coil unit": "FCU",
    "pump": "PUMP",
}


def _normalize(key: str) -> str:
    k = key.upper().replace(" ", "_").replace("-", "_")
    return _EQUIPMENT_TYPE_MAP.get(k, k)


# ─── Public helpers ────────────────────────────────────────────────────────────

def get_defaults(equipment_type: str) -> EquipmentDefaults:
    """Get ASHRAE defaults for an equipment type. Case-insensitive."""
    key = _normalize(equipment_type)
    if key not in ASHRAE_DEFAULTS:
        available = ", ".join(sorted(ASHRAE_DEFAULTS.keys()))
        raise ValueError(
            f"No ASHRAE defaults for '{equipment_type}' ({key}). "
            f"Available types: {available}"
        )
    return ASHRAE_DEFAULTS[key]


def get_default_mtbf(equipment_type: str) -> float:
    return get_defaults(equipment_type).mtbf_hours


def get_default_alpha(equipment_type: str) -> float:
    return get_defaults(equipment_type).alpha_hours


def get_default_beta(equipment_type: str) -> float:
    return get_defaults(equipment_type).beta


def get_service_interval_months(equipment_type: str) -> int:
    return get_defaults(equipment_type).service_interval_months


def get_critical_subcomponents(equipment_type: str) -> List[str]:
    return list(get_defaults(equipment_type).critical_subcomponents)


def get_all_defaults() -> Dict[str, EquipmentDefaults]:
    return dict(ASHRAE_DEFAULTS)


def estimate_rul_days(
    equipment_type: str,
    runtime_hours: float,
    age_years: float,
) -> float:
    """
    Estimate Remaining Useful Life using ASHRAE Weibull parameters.

    Uses age as fraction of characteristic life, then applies Weibull
    inverse survival to get median remaining time.

    Returns RUL in days. Returns 0 if already past characteristic life.
    """
    defaults = get_defaults(equipment_type)
    alpha = defaults.alpha_hours
    beta = defaults.beta

    # Convert age to hours using annual runtime rate
    age_hours = age_years * defaults.runtime_per_year_hours

    if age_hours >= alpha:
        return 0.0

    # Fraction of characteristic life consumed
    age_ratio = age_hours / alpha

    # Weibull median remaining life
    # S(t) = exp(-(t/alpha)^beta) → median: S^-1(0.5) = alpha * (-ln(0.5))^(1/beta)
    # Remaining fraction after age_ratio:
    #   remaining = 1 - age_ratio
    remaining_fraction = 1.0 - age_ratio
    remaining_hours = alpha * remaining_fraction

    rul_days = remaining_hours / 24.0
    return max(0.0, rul_days)


def estimate_failure_probability(
    equipment_type: str,
    runtime_hours: float,
    age_years: float,
) -> float:
    """
    Estimate failure probability using ASHRAE Weibull CDF.

    Returns probability 0..1 that equipment will fail by end of design life.
    """
    defaults = get_defaults(equipment_type)
    alpha = defaults.alpha_hours
    beta = defaults.beta

    age_hours = age_years * defaults.runtime_per_year_hours

    if age_hours <= 0:
        return 0.0

    # Weibull CDF: F(t) = 1 - exp(-(t/alpha)^beta)
    failure_prob = 1.0 - __import__("math").exp(-(age_hours / alpha) ** beta)
    return min(1.0, max(0.0, failure_prob))


def check_service_due(
    equipment_type: str,
    last_service_date: str,   # ISO date string "YYYY-MM-DD"
    current_date: str = None,
) -> bool:
    """Return True if service interval has passed since last_service_date."""
    from datetime import datetime, timedelta

    defaults = get_defaults(equipment_type)
    interval_days = defaults.service_interval_months * 30  # approximate month

    if current_date:
        today = datetime.strptime(current_date, "%Y-%m-%d").date()
    else:
        today = datetime.now().date()

    last = datetime.strptime(last_service_date, "%Y-%m-%d").date()
    elapsed = (today - last).days

    return elapsed >= interval_days
