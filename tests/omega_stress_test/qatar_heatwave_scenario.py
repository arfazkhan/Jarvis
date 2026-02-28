"""
Qatar Heatwave Scenario Generator
==================================

Generates realistic synthetic data for Qatar climate conditions,
building operations, and equipment behavior during heatwave conditions.

Based on real Qatar climate data:
- Summer temperatures: 35-48°C (can reach 50°C+ during heatwaves)
- High humidity: 40-85% (coastal)
- Work week: Sunday-Thursday
- Peak hours: 12:00-18:00 (2x electricity tariff)
"""

import random
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

logger = logging.getLogger("arvis.omega.qatar")


class Season(Enum):
    """Qatar seasons."""
    WINTER = "winter"      # Dec-Feb: 15-25°C
    SPRING = "spring"      # Mar-May: 20-35°C
    SUMMER = "summer"      # Jun-Sep: 35-48°C
    AUTUMN = "autumn"      # Oct-Nov: 25-35°C


class EquipmentType(Enum):
    """Types of building equipment."""
    CHILLER = "chiller"
    AHU = "ahu"
    VAV = "vav"
    COOLING_TOWER = "cooling_tower"
    PUMP = "pump"
    FAN = "fan"


@dataclass
class EquipmentState:
    """State of a piece of equipment."""
    equipment_id: str
    equipment_type: EquipmentType
    status: str = "running"  # running, standby, fault, maintenance
    efficiency: float = 1.0  # 0-1, degrades over time
    runtime_hours: float = 0.0
    last_maintenance: Optional[datetime] = None
    
    # Current readings
    power_kw: float = 0.0
    temperature: float = 0.0
    pressure: float = 0.0
    vibration: float = 0.0
    
    # Fault injection
    fault_probability: float = 0.0
    active_faults: List[str] = field(default_factory=list)


@dataclass
class SensorReading:
    """A single sensor reading."""
    sensor_id: str
    timestamp: datetime
    value: float
    unit: str
    quality: str = "good"  # good, stale, missing, noise
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp.isoformat(),
            "value": round(self.value, 2),
            "unit": self.unit,
            "quality": self.quality,
        }


class QatarClimateModel:
    """
    Realistic Qatar climate simulation.
    
    Based on historical weather data for Doha, Qatar.
    """
    
    # Monthly average temperatures (°C)
    MONTHLY_AVG = {
        1: 18, 2: 19, 3: 23, 4: 28, 5: 34, 6: 38,
        7: 40, 8: 40, 9: 37, 10: 32, 11: 26, 12: 20
    }
    
    # Daily variation amplitude
    DAILY_AMPLITUDE = {
        1: 8, 2: 9, 3: 10, 4: 10, 5: 10, 6: 8,
        7: 6, 8: 6, 9: 8, 10: 10, 11: 10, 12: 8
    }
    
    # Heatwave thresholds
    HEATWAVE_THRESHOLD = 45.0  # °C
    EXTREME_HEATWAVE_THRESHOLD = 48.0  # °C
    
    def __init__(self, start_date: Optional[datetime] = None):
        """
        Initialize climate model.
        
        Args:
            start_date: Starting date for simulation (default: June 1 for summer)
        """
        self.start_date = start_date or datetime(2024, 6, 1)  # Start in summer
        self.heatwave_active = False
        self.heatwave_day = 0
        self.heatwave_intensity = 0.0
    
    def get_outdoor_temp(self, dt: datetime) -> float:
        """Get outdoor temperature for given datetime."""
        month = dt.month
        hour = dt.hour + dt.minute / 60
        
        # Base monthly temperature
        avg_temp = self.MONTHLY_AVG.get(month, 30)
        amplitude = self.DAILY_AMPLITUDE.get(month, 8)
        
        # Daily cycle: min at 5 AM, max at 3 PM
        daily_factor = math.sin((hour - 5) * math.pi / 12)
        
        temp = avg_temp + amplitude * daily_factor
        
        # Add heatwave effect
        if self.heatwave_active:
            temp += self.heatwave_intensity * 5  # Up to 5°C additional
        
        # Add random variation (±2°C)
        temp += random.gauss(0, 1)
        
        return round(temp, 1)
    
    def get_humidity(self, dt: datetime) -> float:
        """Get outdoor relative humidity."""
        month = dt.month
        
        # Higher in summer (coastal humidity)
        base_humidity = 50 + 20 * math.sin((month - 1) * math.pi / 6)
        
        # Lower during hot afternoon
        hour = dt.hour
        if 12 <= hour <= 18:
            base_humidity -= 15
        
        # Random variation
        humidity = base_humidity + random.gauss(0, 5)
        
        return max(20, min(95, humidity))
    
    def start_heatwave(self, intensity: float = 1.0):
        """
        Start a heatwave event.
        
        Args:
            intensity: 0-1, higher = more severe
        """
        self.heatwave_active = True
        self.heatwave_day = 0
        self.heatwave_intensity = intensity
        
        logger.warning(f"HEATWAVE STARTED: intensity={intensity}")
    
    def end_heatwave(self):
        """End the current heatwave."""
        self.heatwave_active = False
        self.heatwave_intensity = 0.0
        
        logger.info("HEATWAVE ENDED")
    
    def advance_day(self):
        """Advance heatwave by one day."""
        if self.heatwave_active:
            self.heatwave_day += 1
            # Intensity can increase over time
            self.heatwave_intensity = min(1.5, self.heatwave_intensity + 0.02)
    
    def get_season(self, dt: datetime) -> Season:
        """Determine season for a date."""
        month = dt.month
        if month in [12, 1, 2]:
            return Season.WINTER
        elif month in [3, 4, 5]:
            return Season.SPRING
        elif month in [6, 7, 8, 9]:
            return Season.SUMMER
        else:
            return Season.AUTUMN


class DohaBuildingModel:
    """
    Simulates a typical Doha office building.
    
    Configuration based on typical Qatar commercial buildings:
    - 20-story office tower
    - 50,000 m² floor area
    - 2 chillers (1200 TR each)
    - 12 AHUs
    - 180 VAVs
    """
    
    def __init__(self, building_id: str = "DOHA-TOWER-001"):
        self.building_id = building_id
        
        # Building parameters
        self.floor_area_m2 = 50000
        self.num_floors = 20
        self.peak_occupancy = 2000
        
        # Initialize equipment
        self.equipment: Dict[str, EquipmentState] = {}
        self._init_equipment()
        
        # Zone temperatures
        self.zone_temps: Dict[str, float] = {}
        self._init_zones()
        
        logger.info(f"Building model initialized: {building_id}")
    
    def _init_equipment(self):
        """Initialize building equipment."""
        # Chillers
        for i in range(1, 3):
            eq_id = f"CH-{i:02d}"
            self.equipment[eq_id] = EquipmentState(
                equipment_id=eq_id,
                equipment_type=EquipmentType.CHILLER,
                efficiency=0.95 if i == 1 else 0.88,  # CH-02 older
                runtime_hours=15000 + i * 5000,
            )
        
        # AHUs
        for i in range(1, 13):
            eq_id = f"AHU-{i:02d}"
            self.equipment[eq_id] = EquipmentState(
                equipment_id=eq_id,
                equipment_type=EquipmentType.AHU,
                efficiency=0.92,
            )
        
        # Cooling Towers
        for i in range(1, 3):
            eq_id = f"CT-{i:02d}"
            self.equipment[eq_id] = EquipmentState(
                equipment_id=eq_id,
                equipment_type=EquipmentType.COOLING_TOWER,
            )
    
    def _init_zones(self):
        """Initialize zone temperatures."""
        for floor in range(1, 21):
            for zone in ['N', 'S', 'E', 'W', 'C']:
                zone_id = f"F{floor:02d}-{zone}"
                self.zone_temps[zone_id] = 23.0  # Initial setpoint
    
    def get_occupancy(self, dt: datetime) -> float:
        """
        Get current occupancy ratio (0-1).
        
        Qatar work week: Sunday-Thursday
        Typical hours: 7 AM - 6 PM
        """
        day = dt.weekday()  # 0=Mon, 6=Sun
        hour = dt.hour
        
        # Friday-Saturday: minimal occupancy
        if day in (4, 5):  # Fri, Sat
            return 0.05
        
        # Work hours
        if 7 <= hour < 9:
            # Arrival ramp
            return 0.3 + (hour - 7) * 0.35
        elif 9 <= hour < 12:
            return 1.0
        elif 12 <= hour < 14:
            # Lunch dip
            return 0.7
        elif 14 <= hour < 17:
            return 0.95
        elif 17 <= hour < 19:
            # Departure ramp
            return 0.9 - (hour - 17) * 0.4
        else:
            return 0.05
    
    def get_equipment_load(self, outdoor_temp: float, occupancy: float) -> float:
        """Calculate total equipment load in kW."""
        # Base load
        base_load = 500  # kW
        
        # Cooling load (increases with outdoor temp)
        cooling_load = max(0, (outdoor_temp - 20) * 50 * occupancy)
        
        # Lighting and plugs
        misc_load = 100 * occupancy
        
        return base_load + cooling_load + misc_load
    
    def update_equipment(self, outdoor_temp: float, hour: int):
        """Update equipment states based on conditions."""
        for eq_id, eq in self.equipment.items():
            if eq.equipment_type == EquipmentType.CHILLER:
                # Chiller power based on load
                load_factor = max(0.3, (outdoor_temp - 20) / 25)
                eq.power_kw = 400 * load_factor * eq.efficiency
                
                # Temperature readings
                eq.temperature = outdoor_temp + random.gauss(0, 1)
                
                # Efficiency degradation in high temps
                if outdoor_temp > 45:
                    eq.efficiency *= 0.998  # Slight degradation
            
            elif eq.equipment_type == EquipmentType.AHU:
                # AHU power
                eq.power_kw = 30 * (0.5 + random.random() * 0.5)
                
                # Supply air temp
                eq.temperature = 14 + random.gauss(0, 0.5)
            
            # Random fault injection
            if random.random() < eq.fault_probability:
                eq.active_faults.append(f"fault_{datetime.now().strftime('%H%M%S')}")
    
    def get_sensor_readings(self, dt: datetime) -> List[SensorReading]:
        """Get all sensor readings for a timestamp."""
        readings = []
        
        # Equipment readings
        for eq_id, eq in self.equipment.items():
            # Power
            readings.append(SensorReading(
                sensor_id=f"{eq_id}-PWR",
                timestamp=dt,
                value=eq.power_kw,
                unit="kW",
            ))
            
            # Temperature
            readings.append(SensorReading(
                sensor_id=f"{eq_id}-TMP",
                timestamp=dt,
                value=eq.temperature,
                unit="°C",
            ))
        
        # Zone temperatures
        for zone_id, temp in self.zone_temps.items():
            readings.append(SensorReading(
                sensor_id=f"{zone_id}-TMP",
                timestamp=dt,
                value=temp + random.gauss(0, 0.3),
                unit="°C",
            ))
        
        return readings
        
    def inject_fault(self, equipment_id: str, fault_type: str):
        """Inject a fault into equipment."""
        if equipment_id in self.equipment:
            eq = self.equipment[equipment_id]
            eq.active_faults.append(fault_type)
            eq.fault_probability = 0.1  # Increase future fault probability
            logger.warning(f"Fault injected: {equipment_id} - {fault_type}")
    
    def resolve_fault(self, equipment_id: str):
        """Resolve all faults and restore efficiency for a piece of equipment."""
        if equipment_id in self.equipment:
            eq = self.equipment[equipment_id]
            eq.active_faults = []
            eq.efficiency = 0.95 if eq.equipment_type == EquipmentType.CHILLER else 0.92
            eq.status = "running"
            eq.last_maintenance = datetime.now()
            logger.info(f"Fault resolved: {equipment_id} (Efficiency restored)")
    
    def inject_data_drop(self, sensor_ids: List[str]):
        """Mark sensors as having missing data."""
        # This would be handled by the synthetic data generator
        pass


class QatarHeatwaveScenario:
    """
    Complete Qatar heatwave scenario generator.
    
    Generates synthetic data for the 90-day pilot stress test.
    """
    
    def __init__(
        self,
        start_date: Optional[datetime] = None,
        seed: Optional[int] = None
    ):
        """
        Initialize scenario generator.
        
        Args:
            start_date: Starting date (default: June 1 for summer)
            seed: Random seed for reproducibility
        """
        if seed is not None:
            random.seed(seed)
        
        self.start_date = start_date or datetime(2024, 6, 1)
        self.current_date = self.start_date
        
        self.climate = QatarClimateModel(self.start_date)
        self.building = DohaBuildingModel()
        
        # Scenario state
        self.day_number = 0
        self.phase = 0
        
        # Event injection
        self.pending_events: List[Dict[str, Any]] = []
        self.scheduled_faults: Dict[int, List[Dict[str, Any]]] = {}
        
        logger.info(
            f"QatarHeatwaveScenario initialized: "
            f"start={self.start_date.strftime('%Y-%m-%d')}"
        )
    
    def advance_day(self) -> Dict[str, Any]:
        """
        Advance simulation by one day.
        
        Returns:
            Daily summary with all generated data
        """
        self.day_number += 1
        self.current_date = self.start_date + timedelta(days=self.day_number - 1)
        
        # Determine phase
        self.phase = self._get_phase(self.day_number)
        
        # Advance climate
        self.climate.advance_day()
        
        # Generate daily data
        daily_data = {
            "day_number": self.day_number,
            "phase": self.phase,
            "date": self.current_date.isoformat(),
            "hourly_data": [],
            "events": [],
            "equipment_states": {},
        }
        
        # Check for scheduled events BEFORE generating hourly data
        if self.day_number in self.scheduled_faults:
            for fault in self.scheduled_faults[self.day_number]:
                self.building.inject_fault(
                    fault["equipment_id"],
                    fault["fault_type"]
                )
                daily_data["events"].append(fault)

        # Generate hourly data
        for hour in range(24):
            hour_dt = self.current_date.replace(hour=hour, minute=0, second=0)
            
            outdoor_temp = self.climate.get_outdoor_temp(hour_dt)
            humidity = self.climate.get_humidity(hour_dt)
            occupancy = self.building.get_occupancy(hour_dt)
            
            # Update equipment
            self.building.update_equipment(outdoor_temp, hour)
            
            hourly = {
                "hour": hour,
                "outdoor_temp": outdoor_temp,
                "humidity": humidity,
                "occupancy": occupancy,
                "equipment_load_kw": self.building.get_equipment_load(outdoor_temp, occupancy),
                "is_peak_hours": 12 <= hour < 18,
                "is_work_hours": 7 <= hour < 18,
                "sensors": [s.to_dict() for s in self.building.get_sensor_readings(hour_dt)],
                "equipment_states": {
                    eq_id: {
                        "status": eq.status,
                        "efficiency": round(eq.efficiency, 3),
                        "power_kw": round(eq.power_kw, 1),
                        "temperature": round(eq.temperature, 1),
                        "vibration": round(eq.vibration, 2),
                        "active_faults": eq.active_faults.copy(),
                        "runtime_hours": round(eq.runtime_hours, 1),
                        "equipment_type": eq.equipment_type.value,
                    }
                    for eq_id, eq in self.building.equipment.items()
                },
                "zone_temps": {
                    zone_id: round(temp + random.gauss(0, 0.3), 1)
                    for zone_id, temp in self.building.zone_temps.items()
                },
            }
            
            daily_data["hourly_data"].append(hourly)
        
        # Store equipment states
        for eq_id, eq in self.building.equipment.items():
            daily_data["equipment_states"][eq_id] = {
                "status": eq.status,
                "efficiency": round(eq.efficiency, 3),
                "power_kw": round(eq.power_kw, 1),
                "active_faults": eq.active_faults.copy(),
            }
        
        return daily_data
    
    def _get_phase(self, day: int) -> int:
        """Determine which phase a day belongs to."""
        if day <= 7:
            return 0
        elif day <= 14:
            return 1
        elif day <= 30:
            return 2
        elif day <= 60:
            return 3
        else:
            return 4
    
    def start_heatwave(self, duration_days: int = 30, intensity: float = 1.0):
        """
        Schedule a heatwave event.
        
        Args:
            duration_days: How long the heatwave lasts
            intensity: Severity (0-1)
        """
        self.climate.start_heatwave(intensity)
        
        # Schedule end
        self.pending_events.append({
            "type": "end_heatwave",
            "day": self.day_number + duration_days,
        })
    
    def schedule_fault(
        self,
        day: int,
        equipment_id: str,
        fault_type: str
    ):
        """
        Schedule a fault to occur on a specific day.
        
        Args:
            day: Day number to inject fault
            equipment_id: Equipment to affect
            fault_type: Type of fault
        """
        if day not in self.scheduled_faults:
            self.scheduled_faults[day] = []
        
        self.scheduled_faults[day].append({
            "type": "equipment_fault",
            "equipment_id": equipment_id,
            "fault_type": fault_type,
        })
    
    def inject_silent_data_drop(
        self,
        sensor_ids: List[str],
        start_hour: int,
        duration_hours: int
    ) -> Dict[str, Any]:
        """
        Inject a silent data drop scenario (Gap 1).
        
        Args:
            sensor_ids: Sensors to drop
            start_hour: Hour to start drop
            duration_hours: Duration of drop
            
        Returns:
            Event description
        """
        return {
            "type": "silent_data_drop",
            "sensor_ids": sensor_ids,
            "start_hour": start_hour,
            "duration_hours": duration_hours,
            "day": self.day_number,
        }
    
    def inject_stale_data(
        self,
        sensor_id: str,
        stale_value: float
    ) -> Dict[str, Any]:
        """
        Inject stale data that looks normal (Gap 1).
        
        Args:
            sensor_id: Sensor to make stale
            stale_value: Value to hold
            
        Returns:
            Event description
        """
        return {
            "type": "stale_data",
            "sensor_id": sensor_id,
            "stale_value": stale_value,
            "day": self.day_number,
        }
    
    def get_daily_summary(self) -> Dict[str, Any]:
        """Get summary of current day."""
        hourly = []
        for hour in range(24):
            hour_dt = self.current_date.replace(hour=hour)
            hourly.append({
                "hour": hour,
                "outdoor_temp": self.climate.get_outdoor_temp(hour_dt),
                "humidity": self.climate.get_humidity(hour_dt),
            })
        
        return {
            "day_number": self.day_number,
            "date": self.current_date.isoformat(),
            "phase": self.phase,
            "heatwave_active": self.climate.heatwave_active,
            "hourly": hourly,
        }
    
    def generate_phase_0_scenario(self) -> List[Dict[str, Any]]:
        """
        Generate complete Phase 0 scenario (Days 1-7).
        
        Cold start - observation without action.
        """
        scenarios = []
        
        for day in range(1, 8):
            scenario = {
                "day": day,
                "phase": 0,
                "conditions": "normal_operations",
                "expected_behavior": "no_advisories",
                "tests": [
                    "P0-001: Data logging without advice",
                    "P0-002: Noise tolerance",
                    "P0-003: Occupancy drift observation",
                    "P0-004: Heatwave vs fault distinction",
                    "P0-005: Memory formation",
                    "P0-006: Baseline lock",
                ],
            }
            scenarios.append(scenario)
        
        return scenarios
    
    def generate_phase_3_scenario(self) -> List[Dict[str, Any]]:
        """
        Generate complete Phase 3 scenario (Days 31-60).
        
        Pressure & Trust Calibration under sustained heatwave.
        """
        scenarios = []
        
        # Start extended heatwave
        self.start_heatwave(duration_days=30, intensity=1.0)
        
        for day in range(31, 61):
            scenario = {
                "day": day,
                "phase": 3,
                "heatwave_day": day - 30,
                "conditions": "sustained_heatwave",
                "tests": [
                    "P3-001: Alarm fatigue resistance",
                    "P3-002: Trust exploitation prevention",
                    "P3-003: Uncertainty feedback request",
                    "P3-004: Greenwashing detection",
                    "P3-005: Institutional risk flagging",
                    "P3-006: Sustained heatwave behavior",
                    "P3-007: Rational human error",
                    "P3-008: Conflicting stakeholders",
                    "P3-009: VIP override scenario",
                ],
            }
            
            # Inject specific events on certain days
            if day == 35:
                scenario["events"] = [
                    self.inject_silent_data_drop(["CH-01-TMP"], 10, 48)
                ]
            
            if day == 45:
                scenario["events"] = [
                    {"type": "vip_visit", "duration_hours": 4}
                ]
            
            scenarios.append(scenario)
        
        return scenarios
