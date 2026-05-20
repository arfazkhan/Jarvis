"""
Qatar Context & Features
==========================

Qatar/GCC-specific data for building operations.
This is DATA, not rules - ML models learn from this context.

Includes:
- KAHRAMAA electricity tariffs
- Qatar calendar (work week, Ramadan, prayer times)
- Typical building profiles
- Environmental patterns
- Equipment specifications
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, time
from enum import Enum
import math


# ═══════════════════════════════════════════════════════════════════════════
# KAHRAMAA ELECTRICITY TARIFFS (2024)
# ═══════════════════════════════════════════════════════════════════════════

KAHRAMAA_TARIFFS = {
    # Electricity rates in QAR/kWh
    "residential_citizen": 0.077,      # Subsidized for Qatari citizens
    "residential_expat": 0.077,        # Same rate
    "commercial_government": 0.16,     # Government buildings
    "commercial_private": 0.23,        # Private sector commercial
    "industrial": 0.14,                # Industrial facilities
    "hotels": 0.23,                    # Hospitality
    "malls": 0.23,                     # Retail
    
    # Water rates in QAR/m³
    "water_residential": 1.5,
    "water_commercial": 4.4,
    
    # No time-of-use pricing currently in Qatar
    "has_tou_pricing": False,
    "peak_multiplier": 1.0,
    
    # Demand charges (if applicable)
    "demand_charge_qar_kva": 0,        # No demand charges
}


# ═══════════════════════════════════════════════════════════════════════════
# QATAR CALENDAR
# ═══════════════════════════════════════════════════════════════════════════

QATAR_CALENDAR = {
    # Work week
    "work_days": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"],
    "weekend_days": ["Friday", "Saturday"],
    "work_day_indices": [6, 0, 1, 2, 3],  # Sunday=6, Mon=0, ..., Thu=3
    "weekend_indices": [4, 5],             # Friday=4, Saturday=5
    
    # Typical office hours
    "office_start": "07:00",
    "office_end": "17:00",
    "office_start_ramadan": "09:00",
    "office_end_ramadan": "14:00",
    
    # Seasons (for cooling load)
    "summer_months": [5, 6, 7, 8, 9],      # May-September (extreme heat)
    "winter_months": [11, 12, 1, 2, 3],    # November-March (mild)
    "transition_months": [4, 10],           # April, October
    
    # Extreme heat threshold
    "extreme_heat_threshold_c": 45,
    "typical_summer_high_c": 46,
    "typical_winter_high_c": 24,
    
    # Sandstorm season
    "sandstorm_months": [3, 4, 5, 6],      # March-June
    "sandstorm_probability_high": 0.15,
    "sandstorm_probability_low": 0.02,
}

# Prayer times (approximate, vary by date)
# Format: (hour, minute) - these shift throughout the year
PRAYER_TIMES_SUMMER = {
    "fajr": (3, 30),
    "sunrise": (5, 0),
    "dhuhr": (11, 30),
    "asr": (15, 0),
    "maghrib": (18, 30),
    "isha": (20, 0),
}

PRAYER_TIMES_WINTER = {
    "fajr": (5, 0),
    "sunrise": (6, 15),
    "dhuhr": (11, 45),
    "asr": (14, 45),
    "maghrib": (17, 15),
    "isha": (18, 30),
}


# ═══════════════════════════════════════════════════════════════════════════
# GSAS (Global Sustainability Assessment System) CRITERIA
# ═══════════════════════════════════════════════════════════════════════════

class GSASRating(Enum):
    """GSAS rating levels"""
    ONE_STAR = 1      # Design practice
    TWO_STAR = 2      # Good practice
    THREE_STAR = 3    # Very good practice
    FOUR_STAR = 4     # Best practice
    FIVE_STAR = 5     # Exemplary practice
    SIX_STAR = 6      # Net zero


GSAS_BENCHMARKS = {
    # Energy Use Intensity benchmarks (kWh/m²/year)
    "eui_office_baseline": 280,
    "eui_office_4star": 180,
    "eui_office_5star": 130,
    
    "eui_hotel_baseline": 350,
    "eui_hotel_4star": 250,
    "eui_hotel_5star": 180,
    
    "eui_mall_baseline": 400,
    "eui_mall_4star": 300,
    "eui_mall_5star": 220,
    
    # Water Use Intensity (L/m²/year)
    "wui_office_baseline": 1500,
    "wui_office_4star": 900,
    
    # Indoor Environmental Quality
    "co2_max_ppm": 800,
    "humidity_min_pct": 30,
    "humidity_max_pct": 60,
    "temp_variance_max_c": 1.5,
    
    # Lighting
    "daylight_autonomy_min_pct": 50,
    "glare_index_max": 22,
}


# ═══════════════════════════════════════════════════════════════════════════
# TYPICAL QATAR BUILDING PROFILES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BuildingProfile:
    """Qatar building profile for simulation"""
    id: str
    name: str
    type: str
    location: str
    
    # Physical
    floors: int
    gfa_sqm: float
    conditioned_area_sqm: float
    
    # HVAC
    cooling_type: str  # "chiller", "dx", "district_cooling"
    cooling_capacity_tons: float
    num_chillers: int
    num_ahus: int
    num_fcu: int
    
    # Operations
    operating_hours: str
    peak_occupancy: int
    gsas_target: GSASRating
    
    # Equipment ages (years)
    building_age: int
    hvac_age: int
    
    # Baseline performance
    baseline_eui: float  # kWh/m²/year
    target_eui: float
    
    # Tags for ML
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "location": self.location,
            "floors": self.floors,
            "gfa_sqm": self.gfa_sqm,
            "cooling_capacity_tons": self.cooling_capacity_tons,
            "num_chillers": self.num_chillers,
            "peak_occupancy": self.peak_occupancy,
            "gsas_target": self.gsas_target.value,
            "baseline_eui": self.baseline_eui,
            "tags": self.tags,
        }


# Realistic Qatar building profiles
QATAR_BUILDINGS = {
    "west_bay_tower_1": BuildingProfile(
        id="WBT-001",
        name="West Bay Commercial Tower",
        type="commercial_office",
        location="West Bay, Doha",
        floors=45,
        gfa_sqm=95000,
        conditioned_area_sqm=85000,
        cooling_type="chiller",
        cooling_capacity_tons=4500,
        num_chillers=4,
        num_ahus=48,
        num_fcu=450,
        operating_hours="06:00-20:00",
        peak_occupancy=3500,
        gsas_target=GSASRating.FOUR_STAR,
        building_age=8,
        hvac_age=8,
        baseline_eui=285,
        target_eui=180,
        tags=["high_rise", "premium", "west_bay", "office"],
    ),
    
    "lusail_mixed_use": BuildingProfile(
        id="LMU-001",
        name="Lusail Mixed-Use Development",
        type="mixed_use",
        location="Lusail City",
        floors=28,
        gfa_sqm=55000,
        conditioned_area_sqm=48000,
        cooling_type="district_cooling",
        cooling_capacity_tons=2200,
        num_chillers=0,  # District cooling
        num_ahus=32,
        num_fcu=280,
        operating_hours="24/7",
        peak_occupancy=1800,
        gsas_target=GSASRating.FIVE_STAR,
        building_age=3,
        hvac_age=3,
        baseline_eui=220,
        target_eui=140,
        tags=["new_build", "district_cooling", "lusail", "mixed_use"],
    ),
    
    "msheireb_commercial": BuildingProfile(
        id="MSH-001",
        name="Msheireb Downtown Building",
        type="commercial_office",
        location="Msheireb, Doha",
        floors=12,
        gfa_sqm=25000,
        conditioned_area_sqm=22000,
        cooling_type="district_cooling",
        cooling_capacity_tons=900,
        num_chillers=0,
        num_ahus=16,
        num_fcu=120,
        operating_hours="07:00-19:00",
        peak_occupancy=800,
        gsas_target=GSASRating.FIVE_STAR,
        building_age=5,
        hvac_age=5,
        baseline_eui=180,
        target_eui=120,
        tags=["heritage", "district_cooling", "msheireb", "sustainable"],
    ),
    
    "pearl_hotel": BuildingProfile(
        id="PHQ-001",
        name="Pearl Qatar Luxury Hotel",
        type="hotel",
        location="Pearl Qatar",
        floors=22,
        gfa_sqm=45000,
        conditioned_area_sqm=40000,
        cooling_type="chiller",
        cooling_capacity_tons=2000,
        num_chillers=3,
        num_ahus=28,
        num_fcu=350,
        operating_hours="24/7",
        peak_occupancy=600,  # Guests + staff
        gsas_target=GSASRating.FOUR_STAR,
        building_age=10,
        hvac_age=10,
        baseline_eui=320,
        target_eui=220,
        tags=["hospitality", "luxury", "pearl_qatar", "24_7"],
    ),
    
    "education_city_facility": BuildingProfile(
        id="ECF-001",
        name="Education City Research Facility",
        type="educational",
        location="Education City",
        floors=6,
        gfa_sqm=35000,
        conditioned_area_sqm=32000,
        cooling_type="chiller",
        cooling_capacity_tons=1400,
        num_chillers=2,
        num_ahus=24,
        num_fcu=180,
        operating_hours="07:00-22:00",
        peak_occupancy=1200,
        gsas_target=GSASRating.FIVE_STAR,
        building_age=7,
        hvac_age=7,
        baseline_eui=250,
        target_eui=160,
        tags=["education", "research", "education_city", "lab"],
    ),
    
    "villagio_mall": BuildingProfile(
        id="VMQ-001",
        name="Villagio-Style Mall",
        type="retail",
        location="Al Waab, Doha",
        floors=3,
        gfa_sqm=180000,
        conditioned_area_sqm=160000,
        cooling_type="chiller",
        cooling_capacity_tons=8000,
        num_chillers=6,
        num_ahus=65,
        num_fcu=800,
        operating_hours="09:00-22:00",
        peak_occupancy=15000,
        gsas_target=GSASRating.THREE_STAR,
        building_age=15,
        hvac_age=12,
        baseline_eui=380,
        target_eui=280,
        tags=["retail", "mall", "high_occupancy", "entertainment"],
    ),
    
    "stadium_venue": BuildingProfile(
        id="STD-001",
        name="FIFA Legacy Stadium",
        type="stadium",
        location="Al Rayyan",
        floors=4,
        gfa_sqm=85000,
        conditioned_area_sqm=45000,  # Not all conditioned
        cooling_type="chiller",
        cooling_capacity_tons=10000,  # Includes field cooling
        num_chillers=8,
        num_ahus=40,
        num_fcu=200,
        operating_hours="event_based",
        peak_occupancy=40000,
        gsas_target=GSASRating.FIVE_STAR,
        building_age=4,
        hvac_age=4,
        baseline_eui=150,
        target_eui=100,
        tags=["stadium", "event", "fifa_legacy", "outdoor_cooling"],
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# OPERATOR PERSONAS (for synthetic preference learning)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass 
class OperatorPersona:
    """Simulated operator for preference learning"""
    id: str
    name: str
    role: str
    experience_years: int
    
    # Preference weights (0-1, higher = more important)
    safety_weight: float
    comfort_weight: float
    energy_weight: float
    cost_weight: float
    speed_weight: float
    gsas_weight: float
    
    # Behavioral traits
    risk_tolerance: float  # 0=risk-averse, 1=risk-seeking
    tech_comfort: float    # 0=traditional, 1=tech-embracing
    autonomy_preference: float  # 0=wants guidance, 1=decides alone
    
    # Work patterns
    typical_shift: str
    decision_speed: str  # "fast", "deliberate", "cautious"
    
    def preference_score(self, option: Dict[str, Any]) -> float:
        """Calculate preference score for an option based on persona"""
        score = 0.0
        
        # Safety (inverse of risk)
        risk = option.get("risk_score", 3) / 5.0
        score += self.safety_weight * (1 - risk)
        
        # Comfort
        comfort = option.get("comfort_score", 3) / 5.0
        score += self.comfort_weight * comfort
        
        # Energy savings
        energy_impact = option.get("energy_impact_pct", 0)
        if energy_impact < 0:  # Saves energy
            score += self.energy_weight * min(1.0, abs(energy_impact) / 20)
        
        # Cost (lower is better)
        cost = option.get("cost_qar", 0)
        cost_score = max(0, 1 - cost / 10000)  # Normalize to 10k QAR
        score += self.cost_weight * cost_score
        
        # Speed (for fast options)
        if option.get("implementation_time_minutes", 60) < 30:
            score += self.speed_weight * 0.5
        
        # GSAS impact
        gsas = option.get("gsas_impact", 0)
        score += self.gsas_weight * max(0, min(1, gsas / 0.1))  # Normalize
        
        # Normalize
        total_weight = (self.safety_weight + self.comfort_weight + 
                       self.energy_weight + self.cost_weight + 
                       self.speed_weight + self.gsas_weight)
        
        return score / total_weight if total_weight > 0 else 0.5


# Realistic operator personas
OPERATOR_PERSONAS = {
    "ahmed_senior_fm": OperatorPersona(
        id="OP-001",
        name="Ahmed Al-Thani",
        role="Senior Facilities Manager",
        experience_years=15,
        safety_weight=0.9,
        comfort_weight=0.7,
        energy_weight=0.5,
        cost_weight=0.6,
        speed_weight=0.3,
        gsas_weight=0.4,
        risk_tolerance=0.2,
        tech_comfort=0.5,
        autonomy_preference=0.8,
        typical_shift="day",
        decision_speed="deliberate",
    ),
    
    "sarah_energy_manager": OperatorPersona(
        id="OP-002",
        name="Sarah Hassan",
        role="Energy & Sustainability Manager",
        experience_years=8,
        safety_weight=0.6,
        comfort_weight=0.5,
        energy_weight=0.95,
        cost_weight=0.4,
        speed_weight=0.3,
        gsas_weight=0.9,
        risk_tolerance=0.4,
        tech_comfort=0.9,
        autonomy_preference=0.6,
        typical_shift="day",
        decision_speed="deliberate",
    ),
    
    "khalid_night_supervisor": OperatorPersona(
        id="OP-003",
        name="Khalid Mohammed",
        role="Night Shift Supervisor",
        experience_years=6,
        safety_weight=0.7,
        comfort_weight=0.4,
        energy_weight=0.3,
        cost_weight=0.3,
        speed_weight=0.9,
        gsas_weight=0.2,
        risk_tolerance=0.5,
        tech_comfort=0.6,
        autonomy_preference=0.4,
        typical_shift="night",
        decision_speed="fast",
    ),
    
    "mohammed_ops_director": OperatorPersona(
        id="OP-004",
        name="Mohammed Al-Sulaiti",
        role="Operations Director",
        experience_years=20,
        safety_weight=0.8,
        comfort_weight=0.8,
        energy_weight=0.6,
        cost_weight=0.9,
        speed_weight=0.2,
        gsas_weight=0.5,
        risk_tolerance=0.3,
        tech_comfort=0.4,
        autonomy_preference=0.9,
        typical_shift="day",
        decision_speed="cautious",
    ),
    
    "fatima_junior_tech": OperatorPersona(
        id="OP-005",
        name="Fatima Al-Ansari",  
        role="Junior HVAC Technician",
        experience_years=2,
        safety_weight=0.5,
        comfort_weight=0.5,
        energy_weight=0.4,
        cost_weight=0.2,
        speed_weight=0.4,
        gsas_weight=0.3,
        risk_tolerance=0.6,
        tech_comfort=0.95,
        autonomy_preference=0.2,
        typical_shift="rotating",
        decision_speed="cautious",
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def is_qatar_working_day(dt: datetime) -> bool:
    """Check if date is a Qatar working day (Sun-Thu)"""
    return dt.weekday() in QATAR_CALENDAR["work_day_indices"]


def is_ramadan(dt: datetime) -> bool:
    """Check if date falls during Ramadan using Hijri calendar conversion."""
    try:
        from hijri_converter import Hijri, Gregorian
        hijri_date = Gregorian(dt.year, dt.month, dt.day).to_hijri()
        return hijri_date.month == 9  # Ramadan is the 9th month in Hijri calendar
    except ImportError:
        # Fallback: approximate using known Ramadan dates (shifts ~11 days/year)
        # Base: 2024 Ramadan started March 11
        base_year = 2024
        base_start_day = 71  # March 11 = day 71 of year
        years_diff = dt.year - base_year
        approx_start_day = base_start_day - int(years_diff * 10.8)
        approx_start_day = approx_start_day % 365
        day_of_year = dt.timetuple().tm_yday
        return approx_start_day <= day_of_year <= approx_start_day + 29


def is_summer(dt: datetime) -> bool:
    """Check if date is during Qatar summer (extreme heat)"""
    return dt.month in QATAR_CALENDAR["summer_months"]


def is_sandstorm_season(dt: datetime) -> bool:
    """Check if date is during sandstorm season"""
    return dt.month in QATAR_CALENDAR["sandstorm_months"]


def get_kahramaa_rate(building_type: str) -> float:
    """Get electricity rate for building type"""
    rate_map = {
        "commercial_office": KAHRAMAA_TARIFFS["commercial_private"],
        "hotel": KAHRAMAA_TARIFFS["hotels"],
        "retail": KAHRAMAA_TARIFFS["malls"],
        "mixed_use": KAHRAMAA_TARIFFS["commercial_private"],
        "educational": KAHRAMAA_TARIFFS["commercial_government"],
        "stadium": KAHRAMAA_TARIFFS["commercial_government"],
        "industrial": KAHRAMAA_TARIFFS["industrial"],
    }
    return rate_map.get(building_type, KAHRAMAA_TARIFFS["commercial_private"])


def get_prayer_times(dt: datetime) -> Dict[str, tuple]:
    """Get prayer times for date"""
    if is_summer(dt):
        return PRAYER_TIMES_SUMMER
    return PRAYER_TIMES_WINTER


def minutes_to_next_prayer(dt: datetime) -> int:
    """Calculate minutes until next prayer"""
    prayers = get_prayer_times(dt)
    current_minutes = dt.hour * 60 + dt.minute
    
    for prayer_name, (hour, minute) in sorted(prayers.items(), key=lambda x: x[1][0]):
        prayer_minutes = hour * 60 + minute
        if prayer_minutes > current_minutes:
            return prayer_minutes - current_minutes
    
    # After isha, next prayer is fajr tomorrow
    fajr_hour, fajr_min = prayers["fajr"]
    return (24 * 60 - current_minutes) + (fajr_hour * 60 + fajr_min)


def calculate_cooling_degree_hours(hour_temps: List[float], base_temp: float = 24) -> float:
    """Calculate cooling degree hours for a day"""
    return sum(max(0, t - base_temp) for t in hour_temps)


def get_building_profile(building_id: str) -> Optional[BuildingProfile]:
    """Get building profile by ID"""
    for key, profile in QATAR_BUILDINGS.items():
        if profile.id == building_id or key == building_id:
            return profile
    return None


def get_operator_persona(operator_id: str) -> Optional[OperatorPersona]:
    """Get operator persona by ID"""
    for key, persona in OPERATOR_PERSONAS.items():
        if persona.id == operator_id or key == operator_id:
            return persona
    return None
