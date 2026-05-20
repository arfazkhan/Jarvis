"""
Realistic BMS Synthetic Data Generator
======================================

Generates synthetic BMS data that mimics real-world building behavior:

1. Climate Model: Qatar temperature profiles (35-48°C summer)
2. Equipment Models: Chiller, AHU, VAV with realistic physics
3. Energy Patterns: Occupancy-driven, time-of-day profiles
4. Failure Scenarios: Degradation, sudden failures, cascade effects
5. Alarm Patterns: Realistic alarm sequences and correlations

This creates a digital twin of a commercial building for testing.
"""

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import numpy as np

from agent_commercial.bms_data_model import (
    Equipment,
    EquipmentType,
    EquipmentStatus,
    BMSDataPoint,
    PointType,
    PointQuality,
    Alarm,
    AlarmSeverity,
    EnergyReading,
)
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.energy_analyzer import EnergyAnalyzer
from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine, EquipmentFeatures

logger = logging.getLogger("arvis.bms.synthetic")


# ═══════════════════════════════════════════════════════════════════════════
# CLIMATE MODEL - QATAR SPECIFIC
# ═══════════════════════════════════════════════════════════════════════════

class QatarClimateModel:
    """
    Realistic Qatar climate simulation.
    
    - Summer (Jun-Sep): 35-48°C, high humidity
    - Winter (Dec-Feb): 15-25°C
    - Daily cycle: Peak at 2-4 PM, low at 5-6 AM
    """
    
    # Monthly average temperatures (°C) — calibrated to Doha climatology.
    # Jun–Aug averages raised to 43–45°C; amplitude 10–12 allows peak 50°C+ hits
    # required to test T3 High-Ambient chiller limits without false anomaly flags.
    MONTHLY_AVG = {
        1: 18, 2: 19, 3: 23, 4: 28, 5: 34, 6: 43,
        7: 45, 8: 45, 9: 39, 10: 32, 11: 26, 12: 20
    }

    # Daily variation amplitude (°C) — larger summer swings due to radiative cooling at night.
    DAILY_AMPLITUDE = {
        1: 8, 2: 9, 3: 10, 4: 10, 5: 10, 6: 10,
        7: 12, 8: 12, 9: 10, 10: 10, 11: 10, 12: 8
    }

    # Urban heat-island offset (°C) for dense West Bay / Lusail districts.
    URBAN_HEAT_ISLAND_C = 2.0
    
    def __init__(self, base_time: Optional[datetime] = None):
        self.base_time = base_time or datetime.now()
    
    def get_outdoor_temp(self, dt: Optional[datetime] = None) -> float:
        """Get outdoor temperature for given datetime"""
        dt = dt or datetime.now()
        month = dt.month
        hour = dt.hour + dt.minute / 60
        
        # Base monthly temperature
        avg_temp = self.MONTHLY_AVG.get(month, 30)
        amplitude = self.DAILY_AMPLITUDE.get(month, 8)
        
        # Daily cycle: min at 5 AM, max at 3 PM
        # Using sine wave shifted to peak at hour 15
        daily_factor = math.sin((hour - 5) * math.pi / 12)
        
        temp = avg_temp + amplitude * daily_factor

        # Random variation + urban heat-island offset
        temp += random.gauss(0, 1) + self.URBAN_HEAT_ISLAND_C

        return round(temp, 1)
    
    def get_humidity(self, dt: Optional[datetime] = None) -> float:
        """Get outdoor relative humidity"""
        dt = dt or datetime.now()
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


# ═══════════════════════════════════════════════════════════════════════════
# BUILDING MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BuildingModel:
    """
    Commercial building model for Qatar.
    
    Typical 20-story office tower:
    - 50,000 m² floor area
    - 2 chillers (1200 TR each)
    - 6 AHUs per chiller
    - Multiple VAVs per AHU
    - Peak occupancy: 2000 people
    """
    building_id: str = "QNB-TOWER-DOHA"
    name: str = "QNB Tower Simulation"
    floor_area_m2: float = 50000
    num_floors: int = 20
    peak_occupancy: int = 2000
    
    # Equipment counts
    num_chillers: int = 2
    chiller_capacity_tr: float = 1200
    num_ahus: int = 12
    num_vavs: int = 180
    
    # Ramadan windows (start, end) — statutory 6h/day / 36h/week limit.
    # Covers 2024–2028; update annually.
    _RAMADAN_RANGES = [
        (date(2024, 3, 11), date(2024, 4, 9)),
        (date(2025, 3,  1), date(2025, 3, 30)),
        (date(2026, 2, 18), date(2026, 3, 19)),
        (date(2027, 2,  8), date(2027, 3,  9)),
        (date(2028, 1, 28), date(2028, 2, 26)),
    ]

    def _is_ramadan(self, dt: datetime) -> bool:
        d = dt.date()
        return any(start <= d <= end for start, end in self._RAMADAN_RANGES)

    def get_occupancy(self, dt: datetime) -> float:
        """
        Occupancy ratio (0–1).

        Qatar work week: Sunday–Thursday (Mon=0, Fri=4, Sat=5).
        Normal hours: 7 AM – 6 PM.
        Ramadan: mandatory 6h/day max → 8 AM – 2 PM per Qatar Labour Law.
        """
        day = dt.weekday()  # 0=Mon … 6=Sun
        hour = dt.hour

        # Friday–Saturday: minimal
        if day in (4, 5):
            return 0.05

        ramadan = self._is_ramadan(dt)

        if ramadan:
            # Compressed Ramadan schedule: 8 AM arrival, 2 PM departure
            if hour < 8:
                return 0.05
            elif 8 <= hour < 9:
                return 0.3 + (hour - 8) * 0.5   # arrival ramp
            elif 9 <= hour < 12:
                return 0.85                       # reduced peak (many staff WFH)
            elif 12 <= hour < 14:
                return 0.5                        # pre-departure wind-down
            elif 14 <= hour < 15:
                return 0.1                        # skeleton staff
            else:
                return 0.05
        else:
            # Normal schedule
            if 7 <= hour < 9:
                return 0.3 + (hour - 7) * 0.35   # arrival ramp
            elif 9 <= hour < 12:
                return 1.0
            elif 12 <= hour < 14:
                return 0.7                        # lunch dip
            elif 14 <= hour < 17:
                return 0.95
            elif 17 <= hour < 19:
                return 0.9 - (hour - 17) * 0.4   # departure ramp
            else:
                return 0.05


# ═══════════════════════════════════════════════════════════════════════════
# EQUIPMENT MODELS
# ═══════════════════════════════════════════════════════════════════════════

class ChillerModel:
    """
    Realistic chiller physics model.
    
    Based on centrifugal chiller characteristics:
    - COP varies with load and condenser temp
    - Surge limit at low loads (<30%)
    - Degradation over time
    """
    
    def __init__(
        self,
        chiller_id: str,
        capacity_tr: float = 1200,
        design_cop: float = 5.5,
        age_years: float = 5.0,
        runtime_hours: float = 15000,
        air_cooled: bool = False,
    ):
        self.chiller_id = chiller_id
        self.capacity_tr = capacity_tr
        self.design_cop = design_cop
        self.age_years = age_years
        self.runtime_hours = runtime_hours
        # air_cooled=True: rooftop DX units, condenser driven by dry-bulb + solar gain.
        # air_cooled=False (default): water-cooled centrifugal, condenser limited by wet-bulb.
        self.air_cooled = air_cooled
        
        # Operating state
        self.is_running = True
        self.current_load = 0.7
        self.current_cop = design_cop
        self.fault_active = False
        
        # Degradation factors
        self.degradation = min(0.3, age_years * 0.02 + runtime_hours * 0.000005)
        
        # Temperatures
        self.chwst = 7.0  # Chilled water supply temp
        self.chwrt = 12.0  # Return temp
        self.condenser_temp = 35.0
    
    @staticmethod
    def _wet_bulb_approx(dry_bulb_c: float, rh_pct: float) -> float:
        """
        Magnus/Stull approximation for wet-bulb temperature (°C).
        Accurate to ±1°C across Qatar operating range (20–50°C, 20–90% RH).
        """
        rh = max(1.0, rh_pct)
        twb = (dry_bulb_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
               + math.atan(dry_bulb_c + rh)
               - math.atan(rh - 1.676331)
               + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
               - 4.686035)
        return twb

    def update(self, outdoor_temp: float, load_fraction: float, outdoor_rh: float = 55.0) -> Dict[str, float]:
        """
        Update chiller state based on conditions.

        Condenser temperature:
        - Air-cooled: dry-bulb + 15°C (solar gain on rooftop plant, Qatar heat rejection penalty).
        - Water-cooled: wet-bulb + 5°C approach (cooling tower limited by latent heat).
        """
        if self.air_cooled:
            self.condenser_temp = outdoor_temp + 15.0
        else:
            twb = self._wet_bulb_approx(outdoor_temp, outdoor_rh)
            self.condenser_temp = twb + 5.0  # 5°C cooling-tower approach
        
        # COP degrades with higher condenser temp and age
        base_cop = self.design_cop * (1 - self.degradation)
        temp_factor = 1 - (self.condenser_temp - 35) * 0.02
        load_factor = 0.85 + 0.15 * min(1.0, load_fraction / 0.5)  # Better COP at higher load
        
        self.current_cop = max(2.0, base_cop * temp_factor * load_factor)
        self.current_load = load_fraction
        
        # Calculate power
        cooling_kw = load_fraction * self.capacity_tr * 3.517  # TR to kW
        power_kw = cooling_kw / self.current_cop
        
        # Simulate realistic variations
        self.chwst = 7.0 + random.gauss(0, 0.2)
        self.chwrt = self.chwst + (12 - 7) * load_fraction + random.gauss(0, 0.3)
        
        return {
            f"{self.chiller_id}/CHWST": round(self.chwst, 1),
            f"{self.chiller_id}/CHWRT": round(self.chwrt, 1),
            f"{self.chiller_id}/LOAD": round(self.current_load * 100, 0),
            f"{self.chiller_id}/KW": round(power_kw, 0),
            f"{self.chiller_id}/COP": round(self.current_cop, 2),
            f"{self.chiller_id}/COND_TEMP": round(self.condenser_temp, 1),
        }
    
    def inject_fault(self, fault_type: str) -> Optional[Alarm]:
        """Inject a fault condition"""
        if fault_type == "low_cop":
            self.degradation += 0.15
            return Alarm(
                equipment_id=self.chiller_id,
                message="Chiller efficiency degraded - COP below threshold",
                severity=AlarmSeverity.HIGH,
            )
        elif fault_type == "trip":
            self.is_running = False
            self.fault_active = True
            return Alarm(
                equipment_id=self.chiller_id,
                message="CHILLER TRIP - Compressor fault",
                severity=AlarmSeverity.CRITICAL,
            )
        return None


class AHUModel:
    """
    Air Handling Unit model.
    
    Mixed air system with:
    - Supply fan with VFD
    - Cooling coil from CHW
    - Outdoor air damper
    - Zone temperature control
    """
    
    def __init__(
        self,
        ahu_id: str,
        design_cfm: float = 20000,
        parent_chiller: str = "",
    ):
        self.ahu_id = ahu_id
        self.design_cfm = design_cfm
        self.parent_chiller = parent_chiller
        
        # Operating state
        self.supply_air_temp = 14.0
        self.return_air_temp = 24.0
        self.fan_speed = 75.0
        self.damper_pos = 20.0
        self.filter_dp = 150  # Pa
        
        # Setpoints
        self.sat_setpoint = 14.0
        self.oa_min = 15.0  # % outdoor air
    
    def update(
        self,
        outdoor_temp: float,
        chw_supply_temp: float,
        zone_temps: List[float],
        occupancy: float,
    ) -> Dict[str, float]:
        """Update AHU state"""
        # Return air is average of zone temps
        self.return_air_temp = np.mean(zone_temps) if zone_temps else 24.0
        
        # Fan speed based on occupancy and zone demand
        self.fan_speed = 40 + 55 * occupancy + random.gauss(0, 2)
        self.fan_speed = max(30, min(100, self.fan_speed))
        
        # Outdoor air damper
        self.damper_pos = max(self.oa_min, 15 + 20 * occupancy)
        
        # Supply air temp - achievable based on CHW temp
        self.supply_air_temp = chw_supply_temp + 5 + random.gauss(0, 0.3)
        
        # Filter DP slowly increases
        self.filter_dp += random.uniform(0, 0.5)
        
        return {
            f"{self.ahu_id}/SAT": round(self.supply_air_temp, 1),
            f"{self.ahu_id}/RAT": round(self.return_air_temp, 1),
            f"{self.ahu_id}/SF_SPD": round(self.fan_speed, 0),
            f"{self.ahu_id}/OA_DMPR": round(self.damper_pos, 0),
            f"{self.ahu_id}/FLT_DP": round(self.filter_dp, 0),
        }
    
    def check_alarms(self) -> List[Alarm]:
        """Check for alarm conditions"""
        alarms = []
        
        if self.filter_dp > 400:
            alarms.append(Alarm(
                equipment_id=self.ahu_id,
                message="Filter differential pressure high - replace filter",
                severity=AlarmSeverity.MEDIUM,
            ))
        
        if self.supply_air_temp > 18:
            alarms.append(Alarm(
                equipment_id=self.ahu_id,
                message="Supply air temperature above setpoint",
                severity=AlarmSeverity.HIGH,
            ))
        
        return alarms


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO GENERATOR
# ═══════════════════════════════════════════════════════════════════════════

class RealisticScenarioGenerator:
    """
    Generate realistic BMS scenarios for testing.
    
    Scenarios:
    1. Normal Operation - typical day
    2. Peak Load - extreme summer afternoon
    3. Chiller Failure - cascade effects
    4. Energy Waste - after-hours HVAC
    5. Gradual Degradation - equipment aging
    6. Alarm Storm - multiple failures
    """
    
    def __init__(self):
        self.climate = QatarClimateModel()
        self.building = BuildingModel()
        
        # Equipment models
        self.chillers: Dict[str, ChillerModel] = {}
        self.ahus: Dict[str, AHUModel] = {}
        
        # State engine
        self.state_engine = BMSStateEngine()
        self.alarm_engine = AlarmEngine()
        self.energy_analyzer = EnergyAnalyzer(electricity_rate_qar=0.14)
        self.pm_engine = PredictiveMaintenanceEngine()
        
        # Time tracking
        self.current_time = datetime.now()
        
        self._initialize_equipment()
    
    def _initialize_equipment(self):
        """Initialize all building equipment"""
        # Chillers
        for i in range(self.building.num_chillers):
            ch_id = f"CH-{i+1:02d}"
            self.chillers[ch_id] = ChillerModel(
                chiller_id=ch_id,
                capacity_tr=self.building.chiller_capacity_tr,
                age_years=random.uniform(3, 8),
                runtime_hours=random.uniform(10000, 25000),
            )
        
        # AHUs
        chiller_ids = list(self.chillers.keys())
        for i in range(self.building.num_ahus):
            ahu_id = f"AHU-{i+1:02d}"
            parent_chiller = chiller_ids[i % len(chiller_ids)]
            self.ahus[ahu_id] = AHUModel(
                ahu_id=ahu_id,
                parent_chiller=parent_chiller,
            )
    
    async def run_scenario(
        self,
        scenario_name: str,
        duration_hours: float = 24,
        time_step_minutes: int = 5,
    ) -> Dict[str, Any]:
        """
        Run a test scenario.
        
        Returns metrics and events from the scenario.
        """
        logger.info(f"Starting scenario: {scenario_name}")
        
        results = {
            "scenario": scenario_name,
            "duration_hours": duration_hours,
            "start_time": self.current_time.isoformat(),
            "data_points": [],
            "alarms": [],
            "energy_readings": [],
            "predictions": [],
            "anomalies": [],
        }
        
        steps = int(duration_hours * 60 / time_step_minutes)
        
        for step in range(steps):
            # Advance time
            self.current_time += timedelta(minutes=time_step_minutes)
            
            # Get conditions
            outdoor_temp = self.climate.get_outdoor_temp(self.current_time)
            outdoor_rh = self.climate.get_humidity(self.current_time)
            occupancy = self.building.get_occupancy(self.current_time)

            # Apply scenario-specific conditions
            outdoor_temp, occupancy = self._apply_scenario(
                scenario_name, step, outdoor_temp, occupancy
            )

            # Update equipment
            data_points = await self._update_equipment(outdoor_temp, occupancy, outdoor_rh)
            results["data_points"].extend(data_points)
            
            # Check alarms
            alarms = await self._check_alarms()
            results["alarms"].extend(alarms)
            
            # Energy readings
            energy = self._get_energy_reading()
            results["energy_readings"].append(energy)
            
            # Every hour, run predictions
            if step % 12 == 0:  # Every 12 steps = 1 hour
                predictions = self._run_predictions()
                results["predictions"].extend(predictions)
            
            # Detect anomalies
            anomalies = self.energy_analyzer.detect_anomalies_realtime(energy)
            results["anomalies"].extend([a.to_dict() for a in anomalies])
        
        results["end_time"] = self.current_time.isoformat()
        results["summary"] = self._generate_summary(results)
        
        return results
    
    def _apply_scenario(
        self,
        scenario: str,
        step: int,
        outdoor_temp: float,
        occupancy: float,
    ) -> Tuple[float, float]:
        """Apply scenario-specific modifications"""
        
        if scenario == "peak_load":
            # Extreme summer afternoon
            outdoor_temp = max(outdoor_temp, 45 + random.uniform(-2, 3))
            occupancy = min(1.0, occupancy + 0.1)
            
        elif scenario == "chiller_failure":
            # Trip chiller at step 20
            if step == 20:
                ch = list(self.chillers.values())[0]
                ch.inject_fault("trip")
                
        elif scenario == "energy_waste":
            # Keep HVAC running after hours
            if self.current_time.hour >= 20 or self.current_time.hour < 6:
                # Normally should be 0.05, we simulate waste
                occupancy = 0.4  # HVAC still running high
                
        elif scenario == "degradation":
            # Accelerate degradation
            for ch in self.chillers.values():
                ch.degradation += 0.001  # Faster wear
                
        elif scenario == "alarm_storm":
            # Multiple simultaneous failures
            if step == 30:
                for ch in self.chillers.values():
                    ch.inject_fault("low_cop")
                for ahu in list(self.ahus.values())[:4]:
                    ahu.filter_dp = 500  # Trigger filter alarms
        
        return outdoor_temp, occupancy
    
    async def _update_equipment(
        self,
        outdoor_temp: float,
        occupancy: float,
        outdoor_rh: float = 55.0,
    ) -> List[BMSDataPoint]:
        """Update all equipment and return data points"""
        all_points = []
        
        # Calculate cooling load
        load_fraction = 0.3 + 0.5 * occupancy + 0.2 * (outdoor_temp - 25) / 20
        load_fraction = max(0.2, min(1.0, load_fraction))
        
        # Update chillers
        chw_temps = []
        for ch_id, chiller in self.chillers.items():
            if chiller.is_running:
                values = chiller.update(outdoor_temp, load_fraction, outdoor_rh)
                chw_temps.append(chiller.chwst)
                
                for point_id, value in values.items():
                    point = BMSDataPoint(
                        point_id=point_id,
                        name=point_id.split("/")[1],
                        value=value,
                        timestamp=self.current_time,
                        equipment_id=ch_id,
                        source="simulator",
                    )
                    all_points.append(point)
                    self.state_engine.update_point_sync(point)
        
        # Average CHW supply temp
        avg_chwst = np.mean(chw_temps) if chw_temps else 10.0
        
        # Update AHUs
        for ahu_id, ahu in self.ahus.items():
            # Simulated zone temps
            zone_temps = [23 + random.gauss(0, 1) for _ in range(6)]
            
            values = ahu.update(outdoor_temp, avg_chwst, zone_temps, occupancy)
            
            for point_id, value in values.items():
                point = BMSDataPoint(
                    point_id=point_id,
                    name=point_id.split("/")[1],
                    value=value,
                    timestamp=self.current_time,
                    equipment_id=ahu_id,
                    source="simulator",
                )
                all_points.append(point)
                self.state_engine.update_point_sync(point)
        
        # Add outdoor temp
        oa_point = BMSDataPoint(
            point_id="WEATHER/OAT",
            name="Outdoor Air Temperature",
            value=outdoor_temp,
            timestamp=self.current_time,
            equipment_id="WEATHER",
            unit="°C",
        )
        all_points.append(oa_point)
        
        return all_points
    
    async def _check_alarms(self) -> List[Dict]:
        """Check equipment for alarm conditions"""
        alarms = []
        
        for ahu in self.ahus.values():
            for alarm in ahu.check_alarms():
                processed = await self.alarm_engine.ingest_alarm(alarm)
                alarms.append(processed.to_dict())
        
        return alarms
    
    def _get_energy_reading(self) -> EnergyReading:
        """Calculate total building energy"""
        total_kw = 0
        
        # Chiller power
        for ch in self.chillers.values():
            if ch.is_running:
                cooling_kw = ch.current_load * ch.capacity_tr * 3.517
                total_kw += cooling_kw / ch.current_cop
        
        # AHU fan power — realistic VFD curve accounts for static pressure
        # and motor losses at low speed (pure cube law gives near-zero, physically wrong).
        # Formula: P = P_rated * (0.1 + 0.9 * (speed_frac)^2.7)
        # At 30% speed: ~3.4 kW (not 0.4 kW from ideal cube law).
        for ahu in self.ahus.values():
            speed_frac = ahu.fan_speed / 100.0
            fan_kw = 15 * (0.1 + 0.9 * speed_frac ** 2.7)
            total_kw += fan_kw
        
        # Non-HVAC loads: lighting + plug loads for 50,000 m² Doha office tower.
        # Baseline 600 kW always-on (12 W/m² servers/common/lighting).
        # Occupancy-driven 650 kW peak (13 W/m² workstations, pantry, AV).
        # Total peak ≈ 1,250 kW → ~25 W/m², per ASHRAE 90.1 Qatar practice.
        occupancy = self.building.get_occupancy(self.current_time)
        total_kw += 600 + 650 * occupancy
        
        reading = EnergyReading(
            meter_id="MAIN-METER",
            value=total_kw,
            unit="kW",
            timestamp=self.current_time,
            outdoor_temp=self.climate.get_outdoor_temp(self.current_time),
            occupancy=occupancy,
        )
        
        self.energy_analyzer.add_reading(reading)
        
        return reading
    
    def _run_predictions(self) -> List[Dict]:
        """Run predictive maintenance on equipment"""
        predictions = []
        
        for ch_id, ch in self.chillers.items():
            features = EquipmentFeatures(
                equipment_id=ch_id,
                runtime_hours=ch.runtime_hours,
                age_years=ch.age_years,
                efficiency=ch.current_cop / ch.design_cop,
                days_since_maintenance=random.randint(30, 120),
                start_stop_cycles=int(ch.runtime_hours / 8),
            )
            
            prediction = self.pm_engine.predict_failure(ch_id, features)
            predictions.append({
                "equipment_id": ch_id,
                "failure_probability": prediction.failure_probability,
                "risk_level": prediction.risk_level,
                "predicted_rul_days": prediction.predicted_rul_days,
            })
        
        return predictions
    
    def _generate_summary(self, results: Dict) -> Dict[str, Any]:
        """Generate scenario summary"""
        return {
            "total_data_points": len(results["data_points"]),
            "total_alarms": len(results["alarms"]),
            "critical_alarms": sum(
                1 for a in results["alarms"]
                if a.get("severity") == "critical" or a.get("alarm", {}).get("severity") == "critical"
            ),
            "total_anomalies": len(results["anomalies"]),
            "total_predictions": len(results["predictions"]),
            "high_risk_equipment": sum(
                1 for p in results["predictions"]
                if p.get("risk_level") in ("high", "critical")
            ),
            "avg_energy_kw": np.mean([
                r.value for r in results["energy_readings"]
            ]) if results["energy_readings"] else 0,
        }


# ═══════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════

async def run_all_scenarios() -> Dict[str, Any]:
    """Run all test scenarios"""
    generator = RealisticScenarioGenerator()
    
    scenarios = [
        "normal_operation",
        "peak_load",
        "chiller_failure",
        "energy_waste",
        "degradation",
        "alarm_storm",
    ]
    
    all_results = {}
    
    for scenario in scenarios:
        print(f"\n{'='*60}")
        print(f"Running scenario: {scenario}")
        print('='*60)
        
        results = await generator.run_scenario(
            scenario_name=scenario,
            duration_hours=4,  # 4 hours per scenario
            time_step_minutes=5,
        )
        
        all_results[scenario] = results
        
        # Print summary
        summary = results["summary"]
        print(f"  Data points generated: {summary['total_data_points']}")
        print(f"  Alarms triggered: {summary['total_alarms']}")
        print(f"  Critical alarms: {summary['critical_alarms']}")
        print(f"  Anomalies detected: {summary['total_anomalies']}")
        print(f"  Average energy (kW): {summary['avg_energy_kw']:.1f}")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(run_all_scenarios())
