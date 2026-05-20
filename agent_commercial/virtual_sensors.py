"""
Virtual Sensors Engine
======================

Software-defined sensors that derive new insights from existing BMS data.

The "Ghost" Detector (Virtual Occupancy Sensing):
- Estimates room occupancy from CO2, VAV position, and lighting
- Detects "Ghost Operations" - cooling empty rooms
- No new hardware required!

This is "Free Hardware" - creating new sensors purely from math.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger("arvis.bms.virtual_sensors")


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

class OccupancyLevel(Enum):
    """Estimated occupancy levels"""
    EMPTY = "empty"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass
class OccupancyEstimate:
    """Virtual occupancy sensor result"""
    zone_id: str
    probability: float  # 0.0 to 1.0
    level: OccupancyLevel
    confidence: float
    contributing_factors: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "probability": round(self.probability, 2),
            "level": self.level.value,
            "confidence": round(self.confidence, 2),
            "factors": self.contributing_factors,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class GhostOperationAlert:
    """Alert for suspected ghost operation (empty room being conditioned)"""
    zone_id: str
    zone_name: str
    alert_type: str = "GHOST_OPERATION"
    severity: str = "MEDIUM"
    scheduled_status: str = "OCCUPIED"
    detected_status: str = "EMPTY"
    occupancy_probability: float = 0.0
    waste_qar_per_hour: float = 0.0
    co2_level: float = 0.0
    recommendation: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "scheduled_status": self.scheduled_status,
            "detected_status": self.detected_status,
            "occupancy_probability": round(self.occupancy_probability, 2),
            "waste_qar_per_hour": round(self.waste_qar_per_hour, 2),
            "co2_level": round(self.co2_level, 0),
            "recommendation": self.recommendation,
            "timestamp": self.timestamp.isoformat(),
        }
    
    def format_message(self) -> str:
        return (
            f"🔍 **Ghost Operation Detected**\n"
            f"• Zone: {self.zone_name}\n"
            f"• Schedule says: {self.scheduled_status}\n"
            f"• Reality: {self.detected_status} (CO2: {self.co2_level:.0f} ppm)\n"
            f"• Wasting: QAR {self.waste_qar_per_hour:.2f}/hour\n"
            f"\n💡 {self.recommendation}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# VIRTUAL OCCUPANCY SENSOR
# ═══════════════════════════════════════════════════════════════════════════

class VirtualOccupancySensor:
    """
    Estimates room occupancy using existing BMS data - no new sensors needed!
    
    Data sources:
    - CO2 levels (primary indicator)
    - VAV damper position
    - Lighting status
    - Historical patterns
    
    This is "Software-Defined Hardware" - deriving new capabilities from
    existing infrastructure.
    """
    
    # CO2 thresholds (ppm)
    CO2_BASELINE = 420      # Empty room (ambient outdoor ~400-420)
    CO2_LOW_OCCUPANCY = 500  # 1-2 people
    CO2_MEDIUM = 650        # Normal meeting
    CO2_HIGH = 900          # Full room / poor ventilation
    
    # Time thresholds
    EMPTY_CONFIRMATION_MINUTES = 30  # Wait 30 min to confirm empty
    
    def __init__(self):
        self.zone_history: Dict[str, List[Tuple[datetime, float]]] = {}
        logger.info("VirtualOccupancySensor initialized")
    
    def estimate_occupancy(
        self,
        zone_id: str,
        co2_ppm: float,
        vav_damper_pct: float = 50.0,
        light_status: bool = True,
        return_air_temp: Optional[float] = None,
    ) -> OccupancyEstimate:
        """
        Estimate zone occupancy probability from sensor data.
        
        Args:
            zone_id: Zone identifier
            co2_ppm: CO2 concentration in parts per million
            vav_damper_pct: VAV damper position (0-100%)
            light_status: Whether lights are on
            return_air_temp: Optional return air temperature
            
        Returns:
            OccupancyEstimate with probability and contributing factors
        """
        factors = {}
        confidence = 0.0
        
        # ─────────────────────────────────────────────────────────────────
        # Factor 1: CO2 Level (Primary - 60% weight)
        # ─────────────────────────────────────────────────────────────────
        if co2_ppm < self.CO2_BASELINE + 50:
            co2_score = 0.0  # Almost certainly empty
            confidence += 0.4  # High confidence when low
        elif co2_ppm < self.CO2_LOW_OCCUPANCY:
            co2_score = 0.2  # Probably empty or just 1 person
            confidence += 0.3
        elif co2_ppm < self.CO2_MEDIUM:
            co2_score = 0.5  # Some occupancy
            confidence += 0.2
        elif co2_ppm < self.CO2_HIGH:
            co2_score = 0.8  # Definitely occupied
            confidence += 0.3
        else:
            co2_score = 1.0  # High occupancy
            confidence += 0.4
        
        factors["co2"] = co2_score
        
        # ─────────────────────────────────────────────────────────────────
        # Factor 2: Lighting (Weak - 15% weight)
        # ─────────────────────────────────────────────────────────────────
        light_score = 0.3 if light_status else 0.0
        factors["lighting"] = light_score
        confidence += 0.15 if not light_status else 0.05
        
        # ─────────────────────────────────────────────────────────────────
        # Factor 3: VAV Damper Behavior (15% weight)
        # ─────────────────────────────────────────────────────────────────
        # If damper is wide open but CO2 is low, something is off
        if vav_damper_pct > 70 and co2_ppm < self.CO2_LOW_OCCUPANCY:
            # Overventilating empty space
            vav_score = 0.1
            factors["vav_conflict"] = -0.2  # Penalty for waste
        elif vav_damper_pct < 30:
            # Minimal ventilation = probably empty
            vav_score = 0.1
        else:
            vav_score = 0.4
        
        factors["vav_behavior"] = vav_score
        
        # ─────────────────────────────────────────────────────────────────
        # Factor 4: Thermal Load (10% weight)
        # ─────────────────────────────────────────────────────────────────
        if return_air_temp is not None:
            # People add heat - warmer return air suggests occupancy
            if return_air_temp > 25:
                thermal_score = 0.6
            elif return_air_temp > 23:
                thermal_score = 0.3
            else:
                thermal_score = 0.1
            factors["thermal_load"] = thermal_score
        
        # ─────────────────────────────────────────────────────────────────
        # Calculate weighted probability
        # ─────────────────────────────────────────────────────────────────
        weights = {
            "co2": 0.60,
            "lighting": 0.15,
            "vav_behavior": 0.15,
            "thermal_load": 0.10,
        }
        
        probability = sum(
            factors.get(key, 0) * weight 
            for key, weight in weights.items()
        )
        
        # Clamp to 0-1
        probability = max(0.0, min(1.0, probability))
        confidence = max(0.0, min(1.0, confidence))
        
        # Determine level
        if probability < 0.15:
            level = OccupancyLevel.EMPTY
        elif probability < 0.35:
            level = OccupancyLevel.LOW
        elif probability < 0.65:
            level = OccupancyLevel.MEDIUM
        else:
            level = OccupancyLevel.HIGH
        
        # Track history
        if zone_id not in self.zone_history:
            self.zone_history[zone_id] = []
        self.zone_history[zone_id].append((datetime.now(), probability))
        
        # Keep only last 2 hours
        cutoff = datetime.now() - timedelta(hours=2)
        self.zone_history[zone_id] = [
            (t, p) for t, p in self.zone_history[zone_id] if t > cutoff
        ]
        
        return OccupancyEstimate(
            zone_id=zone_id,
            probability=probability,
            level=level,
            confidence=confidence,
            contributing_factors=factors,
        )
    
    def detect_ghost_operation(
        self,
        zone_id: str,
        zone_name: str,
        schedule_status: str,
        occupancy_estimate: OccupancyEstimate,
        zone_load_kw: float = 2.0,
        energy_rate: float = 0.14,  # Kahramaa commercial marginal top-tier (2024)
    ) -> Optional[GhostOperationAlert]:
        """
        Detect if a zone is being conditioned while empty ("Ghost Operation").
        
        This is the money-saver: identifying rooms that are scheduled ON
        but physically EMPTY.
        
        Args:
            zone_id: Zone identifier
            zone_name: Human-readable zone name
            schedule_status: "OCCUPIED" or "UNOCCUPIED" per schedule
            occupancy_estimate: Result from estimate_occupancy
            zone_load_kw: Zone cooling/heating load in kW
            energy_rate: QAR per kWh
            
        Returns:
            GhostOperationAlert if detected, None otherwise
        """
        is_scheduled_on = schedule_status.upper() in ["OCCUPIED", "ON", "SCHEDULED"]
        is_physically_empty = occupancy_estimate.probability < 0.20
        
        # Need both conditions AND sufficient confidence
        if is_scheduled_on and is_physically_empty and occupancy_estimate.confidence > 0.5:
            
            # Check if this has been sustained (not just a brief empty period)
            history = self.zone_history.get(zone_id, [])
            if len(history) >= 3:
                recent_probs = [p for t, p in history[-6:]]
                avg_prob = sum(recent_probs) / len(recent_probs)
                
                # Need sustained low occupancy
                if avg_prob > 0.25:
                    return None  # False alarm
            
            # Calculate waste
            waste_per_hour = zone_load_kw * energy_rate
            
            return GhostOperationAlert(
                zone_id=zone_id,
                zone_name=zone_name,
                occupancy_probability=occupancy_estimate.probability,
                waste_qar_per_hour=waste_per_hour,
                co2_level=occupancy_estimate.contributing_factors.get("co2", 0) * 1000 + 400,
                recommendation=(
                    f"Consider switching to 'Standby' mode (setback 2°C) "
                    f"or turning off HVAC. Potential savings: QAR {waste_per_hour * 8:.0f}/day."
                ),
            )
        
        return None
    
    def scan_all_zones(
        self,
        zones: List[Dict[str, Any]],
    ) -> List[GhostOperationAlert]:
        """
        Scan all zones for ghost operations.
        
        Args:
            zones: List of zone dicts with sensor data
            
        Returns:
            List of ghost operation alerts
        """
        alerts = []
        
        for zone in zones:
            zone_id = zone.get("zone_id", "unknown")
            zone_name = zone.get("name", zone_id)
            
            # Estimate occupancy
            estimate = self.estimate_occupancy(
                zone_id=zone_id,
                co2_ppm=zone.get("co2_ppm", 420),
                vav_damper_pct=zone.get("vav_damper_pct", 50),
                light_status=zone.get("light_status", True),
                return_air_temp=zone.get("return_air_temp"),
            )
            
            # Check for ghost operation
            alert = self.detect_ghost_operation(
                zone_id=zone_id,
                zone_name=zone_name,
                schedule_status=zone.get("schedule_status", "OCCUPIED"),
                occupancy_estimate=estimate,
                zone_load_kw=zone.get("load_kw", 2.0),
            )
            
            if alert:
                alerts.append(alert)
        
        return alerts


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS (LLM Tool Integration)
# ═══════════════════════════════════════════════════════════════════════════

def find_ghost_spaces(
    zones: Optional[List[Dict[str, Any]]] = None,
    floor_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Scan for ghost operations (empty rooms being cooled/heated).
    
    This is the LLM tool handler.
    """
    sensor = VirtualOccupancySensor()
    
    # If no zones provided, use sample data
    if zones is None:
        zones = [
            {"zone_id": "CONF-01", "name": "Conference Room A", "co2_ppm": 410, "schedule_status": "OCCUPIED", "vav_damper_pct": 60},
            {"zone_id": "CONF-02", "name": "Conference Room B", "co2_ppm": 680, "schedule_status": "OCCUPIED", "vav_damper_pct": 75},
            {"zone_id": "OFFICE-01", "name": "Open Office Floor 3", "co2_ppm": 720, "schedule_status": "OCCUPIED", "vav_damper_pct": 80},
            {"zone_id": "LOBBY-01", "name": "Main Lobby", "co2_ppm": 430, "schedule_status": "OCCUPIED", "vav_damper_pct": 50},
        ]
    
    # Filter by floor if specified
    if floor_filter:
        zones = [z for z in zones if floor_filter.lower() in z.get("name", "").lower()]
    
    alerts = sensor.scan_all_zones(zones)
    
    return {
        "zones_scanned": len(zones),
        "ghosts_found": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
        "total_waste_qar_hour": sum(a.waste_qar_per_hour for a in alerts),
        "summary": (
            f"Found {len(alerts)} ghost operations. "
            f"Total potential savings: QAR {sum(a.waste_qar_per_hour for a in alerts):.2f}/hour"
            if alerts else "No ghost operations detected. All zones appear appropriately occupied."
        ),
    }


def estimate_zone_occupancy(
    zone_id: str,
    co2_ppm: float,
    vav_damper_pct: float = 50,
    light_status: bool = True,
) -> Dict[str, Any]:
    """
    Estimate occupancy for a single zone.
    
    This is the LLM tool handler.
    """
    sensor = VirtualOccupancySensor()
    estimate = sensor.estimate_occupancy(
        zone_id=zone_id,
        co2_ppm=co2_ppm,
        vav_damper_pct=vav_damper_pct,
        light_status=light_status,
    )
    return estimate.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# VIRTUAL SUPPLY AIR TEMPERATURE SENSOR
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SATEstimate:
    """Virtual supply air temperature sensor result."""
    equipment_id: str
    estimated_sat_c: float
    confidence: float
    method: str
    inputs_used: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "estimated_sat_c": round(self.estimated_sat_c, 2),
            "confidence": round(self.confidence, 2),
            "method": self.method,
            "inputs_used": {k: round(v, 2) for k, v in self.inputs_used.items()},
            "timestamp": self.timestamp.isoformat(),
        }


class VirtualSATSensor:
    """
    Derives supply air temperature from existing BMS data — no new probe needed.

    Two derivation methods (used in order of input availability):

    Method 1: Energy Balance
        SAT = MAT - (Q_cooling / (m_dot * Cp_air))
        where:
          MAT = mixed air temperature (°C)
          Q_cooling = cooling_valve_pct/100 * rated_cooling_kw * 3600 (kJ/h)
          m_dot = airflow_m3h * rho_air (kg/h)
          Cp_air = 1.006 kJ/(kg·K)

    Method 2: Zone Thermal Inference
        When zone return air temp and fan speed are available but MAT is not.
        SAT ≈ zone_rat - (zone_rat - design_sat) * (fan_speed/100)
        This is a simplified steady-state approximation.

    Confidence degrades gracefully as inputs are unavailable.
    """

    CP_AIR = 1.006        # kJ/(kg·K)
    RHO_AIR = 1.2         # kg/m³ at ~20°C
    DESIGN_SAT_C = 13.0   # Typical AHU design SAT for commercial buildings
    DEFAULT_RATED_KW = 50.0  # Default AHU rated cooling capacity (kW)

    def estimate_sat(
        self,
        equipment_id: str,
        mixed_air_temp_c: Optional[float] = None,
        cooling_valve_pct: Optional[float] = None,
        airflow_m3h: Optional[float] = None,
        rated_cooling_kw: Optional[float] = None,
        return_air_temp_c: Optional[float] = None,
        fan_speed_pct: Optional[float] = None,
        actual_sat_c: Optional[float] = None,
    ) -> SATEstimate:
        """
        Estimate supply air temperature from available BMS inputs.

        Args:
            equipment_id: AHU identifier
            mixed_air_temp_c: Mixed air temperature at AHU inlet (°C)
            cooling_valve_pct: Cooling coil valve position (0-100%)
            airflow_m3h: Supply fan airflow rate (m³/h)
            rated_cooling_kw: AHU rated cooling capacity (kW)
            return_air_temp_c: Return air temperature (°C)
            fan_speed_pct: Supply fan speed (%)
            actual_sat_c: Actual SAT if available — used to calibrate confidence

        Returns:
            SATEstimate with derived SAT and confidence level
        """
        inputs_used: Dict[str, float] = {}

        # ── Method 1: Energy Balance ──────────────────────────────────────
        if mixed_air_temp_c is not None and cooling_valve_pct is not None:
            inputs_used["mixed_air_temp_c"] = mixed_air_temp_c
            inputs_used["cooling_valve_pct"] = cooling_valve_pct

            q_kw = (cooling_valve_pct / 100.0) * (rated_cooling_kw or self.DEFAULT_RATED_KW)

            if airflow_m3h and airflow_m3h > 0:
                inputs_used["airflow_m3h"] = airflow_m3h
                m_dot_kg_s = (airflow_m3h * self.RHO_AIR) / 3600.0
                delta_t = q_kw / (m_dot_kg_s * self.CP_AIR * 1000.0)
                confidence = 0.85
            else:
                # Default to typical AHU airflow (5000 m³/h)
                m_dot_kg_s = (5000 * self.RHO_AIR) / 3600.0
                delta_t = q_kw / (m_dot_kg_s * self.CP_AIR * 1000.0)
                confidence = 0.65

            estimated_sat = mixed_air_temp_c - delta_t

            # Calibrate confidence against actual if provided
            if actual_sat_c is not None:
                error = abs(estimated_sat - actual_sat_c)
                calibration_penalty = min(0.3, error * 0.05)
                confidence = max(0.3, confidence - calibration_penalty)

            return SATEstimate(
                equipment_id=equipment_id,
                estimated_sat_c=round(float(estimated_sat), 2),
                confidence=confidence,
                method="energy_balance",
                inputs_used=inputs_used,
            )

        # ── Method 2: Zone Thermal Inference ─────────────────────────────
        if return_air_temp_c is not None and fan_speed_pct is not None:
            inputs_used["return_air_temp_c"] = return_air_temp_c
            inputs_used["fan_speed_pct"] = fan_speed_pct

            # Steady-state approximation: higher fan speed → SAT closer to design
            fan_ratio = min(1.0, fan_speed_pct / 100.0)
            estimated_sat = return_air_temp_c - (return_air_temp_c - self.DESIGN_SAT_C) * fan_ratio * 0.6
            confidence = 0.50

            if cooling_valve_pct is not None:
                inputs_used["cooling_valve_pct"] = cooling_valve_pct
                valve_correction = (cooling_valve_pct / 100.0) * 2.0
                estimated_sat -= valve_correction
                confidence = 0.58

            return SATEstimate(
                equipment_id=equipment_id,
                estimated_sat_c=round(float(estimated_sat), 2),
                confidence=confidence,
                method="zone_thermal_inference",
                inputs_used=inputs_used,
            )

        # ── Fallback: Design default ──────────────────────────────────────
        return SATEstimate(
            equipment_id=equipment_id,
            estimated_sat_c=self.DESIGN_SAT_C,
            confidence=0.20,
            method="design_default",
            inputs_used=inputs_used,
        )


def estimate_virtual_sat(
    equipment_id: str,
    mixed_air_temp_c: Optional[float] = None,
    cooling_valve_pct: Optional[float] = None,
    airflow_m3h: Optional[float] = None,
    rated_cooling_kw: Optional[float] = None,
    return_air_temp_c: Optional[float] = None,
    fan_speed_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """LLM tool handler for virtual SAT estimation."""
    sensor = VirtualSATSensor()
    result = sensor.estimate_sat(
        equipment_id=equipment_id,
        mixed_air_temp_c=mixed_air_temp_c,
        cooling_valve_pct=cooling_valve_pct,
        airflow_m3h=airflow_m3h,
        rated_cooling_kw=rated_cooling_kw,
        return_air_temp_c=return_air_temp_c,
        fan_speed_pct=fan_speed_pct,
    )
    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# VIRTUAL SENSOR REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class VirtualSensorRegistry:
    """
    Central registry for all ARVIS virtual sensors.
    Register sensors once on startup; query them by ID from API or tool handlers.
    """

    def __init__(self):
        self._sensors: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        sensor_id: str,
        sensor_obj: Any,
        sensor_type: str,
        description: str,
        equipment_ids: List[str],
    ) -> None:
        """
        Register a virtual sensor.

        Args:
            sensor_id: Unique identifier (e.g. 'vsat_AHU-01', 'vocc_ZONE-01')
            sensor_obj: Sensor instance (VirtualSATSensor or VirtualOccupancySensor)
            sensor_type: 'sat' or 'occupancy'
            description: Human-readable description
            equipment_ids: List of equipment/zone IDs served by this sensor
        """
        self._sensors[sensor_id] = {
            "sensor_id": sensor_id,
            "sensor_obj": sensor_obj,
            "sensor_type": sensor_type,
            "description": description,
            "equipment_ids": equipment_ids,
            "registered_at": datetime.now().isoformat(),
        }
        logger.debug(f"Virtual sensor registered: {sensor_id} (type={sensor_type})")

    def get_all_registered(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered sensors (no sensor object included)."""
        result = []
        for entry in self._sensors.values():
            result.append({
                "sensor_id": entry["sensor_id"],
                "sensor_type": entry["sensor_type"],
                "description": entry["description"],
                "equipment_ids": entry["equipment_ids"],
                "registered_at": entry["registered_at"],
            })
        return result

    def read(self, sensor_id: str, **kwargs) -> Dict[str, Any]:
        """
        Read a registered virtual sensor.

        Calls the appropriate sensor method based on sensor_type:
          - 'sat'       → VirtualSATSensor.estimate_sat(equipment_id, **kwargs)
          - 'occupancy' → VirtualOccupancySensor.estimate_occupancy(zone_id, **kwargs)

        Returns:
            Result dict from the sensor, or error dict if sensor not found / call fails.
        """
        entry = self._sensors.get(sensor_id)
        if entry is None:
            return {"error": f"Virtual sensor '{sensor_id}' not registered"}

        sensor_obj = entry["sensor_obj"]
        sensor_type = entry["sensor_type"]
        equipment_ids = entry["equipment_ids"]

        # Resolve the primary equipment / zone ID
        primary_id = equipment_ids[0] if equipment_ids else sensor_id

        try:
            if sensor_type == "sat":
                equipment_id = kwargs.pop("equipment_id", primary_id)
                result = sensor_obj.estimate_sat(equipment_id=equipment_id, **kwargs)
                return result.to_dict()

            elif sensor_type == "occupancy":
                zone_id = kwargs.pop("zone_id", primary_id)
                result = sensor_obj.estimate_occupancy(zone_id=zone_id, **kwargs)
                return result.to_dict()

            else:
                return {"error": f"Unknown sensor_type '{sensor_type}' for sensor '{sensor_id}'"}

        except Exception as exc:
            logger.error(f"VirtualSensorRegistry.read({sensor_id}) failed: {exc}")
            return {"error": str(exc), "sensor_id": sensor_id}

    def __len__(self) -> int:
        return len(self._sensors)

    def __contains__(self, sensor_id: str) -> bool:
        return sensor_id in self._sensors


# ── Module-level singleton ────────────────────────────────────────────────

_registry_instance: Optional[VirtualSensorRegistry] = None


def get_registry() -> VirtualSensorRegistry:
    """Return the module-level VirtualSensorRegistry singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = VirtualSensorRegistry()
        logger.debug("VirtualSensorRegistry singleton created")
    return _registry_instance
