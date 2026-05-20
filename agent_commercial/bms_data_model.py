"""
BMS Data Models
===============

Core data structures for Building Management System integration.
These models represent equipment, data points, alarms, and readings
in a vendor-neutral format that works with BACnet, Modbus, and REST APIs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class EquipmentType(Enum):
    """Types of BMS equipment"""
    AHU = "air_handling_unit"
    CHILLER = "chiller"
    BOILER = "boiler"
    COOLING_TOWER = "cooling_tower"
    VAV = "variable_air_volume"
    FCU = "fan_coil_unit"
    PUMP = "pump"
    FAN = "fan"
    DAMPER = "damper"
    VALVE = "valve"
    VFD = "variable_frequency_drive"
    METER_ELECTRIC = "electric_meter"
    METER_WATER = "water_meter"
    METER_GAS = "gas_meter"
    LIGHTING_PANEL = "lighting_panel"
    BMS_CONTROLLER = "bms_controller"
    SENSOR = "sensor"
    OTHER = "other"


class PointType(Enum):
    """Types of BMS data points"""
    SENSOR = "sensor"           # Read-only measurement (temperature, pressure)
    SETPOINT = "setpoint"       # Configurable target value
    STATUS = "status"           # Binary/enum state (on/off, mode)
    COMMAND = "command"         # Control output (start/stop)
    ALARM = "alarm"             # Alarm/fault condition
    COUNTER = "counter"         # Accumulated value (runtime hours)
    CALCULATED = "calculated"   # Derived value (efficiency)


class PointQuality(Enum):
    """Data quality indicators"""
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    STALE = "stale"             # No update in expected interval
    OVERRIDDEN = "overridden"   # Manual override active


class AlarmSeverity(Enum):
    """Alarm severity levels"""
    CRITICAL = "critical"       # Immediate action required, safety risk
    HIGH = "high"               # Urgent, significant impact
    MEDIUM = "medium"           # Should address soon
    LOW = "low"                 # Informational, minor issue
    INFO = "info"               # Notification only


class AlarmState(Enum):
    """Alarm lifecycle states"""
    ACTIVE = "active"           # Currently in alarm
    ACKNOWLEDGED = "acknowledged"  # Seen but not resolved
    RESOLVED = "resolved"       # Condition cleared
    SUPPRESSED = "suppressed"   # Intentionally silenced


class EquipmentStatus(Enum):
    """Equipment operational status"""
    RUNNING = "running"
    STOPPED = "stopped"
    STANDBY = "standby"
    FAULT = "fault"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BMSDataPoint:
    """
    Universal BMS data point.
    
    Represents a single measurement, setpoint, or status value
    from any BMS protocol (BACnet, Modbus, API).
    
    Attributes:
        point_id: Unique identifier (e.g., "AHU-01/SAT")
        name: Human-readable name (e.g., "Supply Air Temperature")
        value: Current value (float for measurements, can be None)
        unit: Engineering unit (e.g., "°C", "kW", "%", "psi")
        timestamp: When this value was read/updated
        source: Protocol source ("bacnet", "modbus", "api", "simulator")
        equipment_id: Parent equipment ID
        point_type: Category of point (sensor, setpoint, etc.)
        quality: Data quality indicator
        
    Example:
        >>> point = BMSDataPoint(
        ...     point_id="AHU-01/SAT",
        ...     name="Supply Air Temperature",
        ...     value=18.5,
        ...     unit="°C",
        ...     equipment_id="AHU-01"
        ... )
    """
    point_id: str
    name: str
    value: Optional[float] = None
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "unknown"
    equipment_id: str = ""
    point_type: PointType = PointType.SENSOR
    quality: PointQuality = PointQuality.GOOD
    
    # BACnet-specific (optional)
    bacnet_device_id: Optional[int] = None
    bacnet_object_type: Optional[str] = None
    bacnet_object_instance: Optional[int] = None
    
    # Modbus-specific (optional)
    modbus_address: Optional[int] = None
    modbus_register_type: Optional[str] = None
    
    # History buffer (last N values for trend analysis)
    history: List[tuple] = field(default_factory=list)  # [(timestamp, value), ...]
    
    def add_to_history(self, max_size: int = 1440):  # 24h at 1-min intervals
        """Add current value to history buffer"""
        if self.value is not None:
            self.history.append((self.timestamp, self.value))
            if len(self.history) > max_size:
                self.history.pop(0)
    
    def get_trend(self, minutes: int = 60) -> List[float]:
        """Get recent values for trend analysis"""
        cutoff = datetime.now().timestamp() - (minutes * 60)
        return [v for t, v in self.history if t.timestamp() > cutoff]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "point_id": self.point_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "equipment_id": self.equipment_id,
            "point_type": self.point_type.value,
            "quality": self.quality.value,
        }


@dataclass
class Equipment:
    """
    BMS equipment entity.
    
    Represents a piece of building equipment (AHU, Chiller, VAV, etc.)
    with its associated data points and operational metrics.
    
    Attributes:
        equipment_id: Unique identifier (e.g., "AHU-01")
        name: Human-readable name (e.g., "Air Handler Unit 1")
        equipment_type: Category of equipment
        location: Physical location (e.g., "Building A, Floor 3, Zone 1")
        data_points: List of associated point IDs
        status: Current operational status
        
    ML-Relevant Metrics:
        runtime_hours: Total operating hours (degradation indicator)
        start_stop_cycles: Number of starts (wear indicator)
        last_maintenance: Date of last service
        efficiency: Current operating efficiency (degradation indicator)
    """
    equipment_id: str
    name: str
    equipment_type: EquipmentType = EquipmentType.OTHER
    location: str = ""
    data_points: List[str] = field(default_factory=list)
    status: EquipmentStatus = EquipmentStatus.UNKNOWN
    
    # Operational metrics (for predictive maintenance ML)
    runtime_hours: float = 0.0
    start_stop_cycles: int = 0
    last_maintenance: Optional[datetime] = None
    next_maintenance_due: Optional[datetime] = None
    efficiency: Optional[float] = None  # 0.0 - 1.0
    
    # Metadata
    manufacturer: str = ""
    model: str = ""
    install_date: Optional[datetime] = None
    expected_lifespan_years: Optional[float] = None
    
    # Parent-child relationships (for topology)
    parent_equipment_id: Optional[str] = None
    child_equipment_ids: List[str] = field(default_factory=list)
    
    # Active alarms
    active_alarm_ids: List[str] = field(default_factory=list)
    
    def get_age_years(self) -> Optional[float]:
        """Calculate equipment age in years"""
        if self.install_date:
            delta = datetime.now() - self.install_date
            return delta.days / 365.25
        return None
    
    def get_maintenance_overdue_days(self) -> Optional[int]:
        """Days overdue for maintenance (negative if not due yet)"""
        if self.next_maintenance_due:
            delta = datetime.now() - self.next_maintenance_due
            return delta.days
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "equipment_id": self.equipment_id,
            "name": self.name,
            "equipment_type": self.equipment_type.value,
            "location": self.location,
            "status": self.status.value,
            "runtime_hours": self.runtime_hours,
            "start_stop_cycles": self.start_stop_cycles,
            "last_maintenance": self.last_maintenance.isoformat() if self.last_maintenance else None,
            "efficiency": self.efficiency,
            "active_alarms": len(self.active_alarm_ids),
            "data_point_count": len(self.data_points),
        }


@dataclass
class Alarm:
    """
    BMS alarm/event.
    
    Represents an abnormal condition detected by the BMS.
    
    Attributes:
        alarm_id: Unique identifier
        source_point_id: Data point that triggered the alarm
        equipment_id: Associated equipment
        message: Human-readable alarm description
        severity: Criticality level
        state: Lifecycle state (active, acknowledged, resolved)
        
    For Alarm Engine:
        cluster_id: ID of alarm cluster (for root cause grouping)
        root_cause_probability: Likelihood this is the root cause (0-1)
    """
    alarm_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_point_id: str = ""
    equipment_id: str = ""
    message: str = ""
    severity: AlarmSeverity = AlarmSeverity.MEDIUM
    state: AlarmState = AlarmState.ACTIVE
    
    # Timestamps
    triggered_at: datetime = field(default_factory=datetime.now)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Who/what
    acknowledged_by: Optional[str] = None
    
    # Alarm engine metadata
    cluster_id: Optional[str] = None
    root_cause_probability: float = 0.0
    related_alarm_ids: List[str] = field(default_factory=list)
    
    # Impact estimation
    comfort_impact: float = 0.0  # 0-1, how much it affects occupant comfort
    energy_impact: float = 0.0   # 0-1, how much it affects energy consumption
    safety_impact: float = 0.0   # 0-1, how much it affects safety
    
    # BACnet event info (optional)
    bacnet_event_type: Optional[str] = None
    bacnet_notify_type: Optional[str] = None
    
    def duration_minutes(self) -> float:
        """Get alarm duration in minutes"""
        end_time = self.resolved_at or datetime.now()
        delta = end_time - self.triggered_at
        return delta.total_seconds() / 60
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "alarm_id": self.alarm_id,
            "source_point_id": self.source_point_id,
            "equipment_id": self.equipment_id,
            "message": self.message,
            "severity": self.severity.value,
            "state": self.state.value,
            "triggered_at": self.triggered_at.isoformat(),
            "duration_minutes": self.duration_minutes(),
            "cluster_id": self.cluster_id,
            "root_cause_probability": self.root_cause_probability,
        }


@dataclass
class EnergyReading:
    """
    Energy consumption reading.
    
    Used for energy anomaly detection and baseline modeling.
    
    Attributes:
        meter_id: Energy meter identifier
        value: Energy value (kWh, kW, etc.)
        unit: Engineering unit
        timestamp: When reading was taken
        
    Context (for ML features):
        outdoor_temp: Outside temperature at time of reading
        occupancy: Building occupancy level (0-1)
        is_workday: Whether it's a working day
        hour_of_day: 0-23
        day_of_week: 0-6 (Monday=0)
    """
    meter_id: str
    value: float
    unit: str = "kWh"
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Context for ML features
    outdoor_temp: Optional[float] = None
    occupancy: Optional[float] = None  # 0.0 - 1.0
    is_workday: Optional[bool] = None
    
    @property
    def hour_of_day(self) -> int:
        return self.timestamp.hour
    
    @property
    def day_of_week(self) -> int:
        return self.timestamp.weekday()
    
    def to_feature_vector(self) -> List[float]:
        """Convert to feature vector for ML model"""
        return [
            self.hour_of_day,
            self.day_of_week,
            self.outdoor_temp or 0.0,
            self.occupancy or 0.5,
            1.0 if self.is_workday else 0.0,
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "meter_id": self.meter_id,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "outdoor_temp": self.outdoor_temp,
            "occupancy": self.occupancy,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ML OUTPUT MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Anomaly:
    """
    Detected anomaly from Isolation Forest or other ML model.
    """
    anomaly_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    anomaly_type: str = ""  # "energy_spike", "energy_drop", "pattern_violation"
    severity: float = 0.0   # 0.0 - 1.0
    source_id: str = ""     # Equipment or meter ID
    
    detected_value: float = 0.0
    expected_value: float = 0.0
    deviation_percent: float = 0.0
    
    timestamp: datetime = field(default_factory=datetime.now)
    description: str = ""
    
    # Potential savings if addressed
    estimated_annual_savings_qar: float = 0.0


@dataclass
class FailurePrediction:
    """
    Output from predictive maintenance ML model.
    """
    equipment_id: str
    failure_probability: float      # 0.0 - 1.0 (probability of failure in next 7 days)
    risk_level: str                 # "low" | "medium" | "high" | "critical"
    predicted_rul_days: int         # Remaining Useful Life in days (-1 if unknown)
    confidence: float               # Model confidence 0.0 - 1.0

    recommendation: str             # Actionable recommendation
    contributing_factors: List[Dict[str, Any]] = field(default_factory=list)
    failure_probability_horizons: Dict[str, float] = field(default_factory=dict)

    predicted_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "equipment_id": self.equipment_id,
            "failure_probability": round(self.failure_probability, 3),
            "risk_level": self.risk_level,
            "predicted_rul_days": self.predicted_rul_days,
            "confidence": round(self.confidence, 3),
            "recommendation": self.recommendation,
            "contributing_factors": self.contributing_factors,
            "predicted_at": self.predicted_at.isoformat(),
        }
        if self.failure_probability_horizons:
            d["failure_probability_horizons"] = {
                k: round(v, 3) for k, v in self.failure_probability_horizons.items()
            }
        return d


@dataclass 
class OpsInsight:
    """
    AI-generated insight for facility managers.
    
    This is what gets shown in the Ops Copilot dashboard.
    """
    insight_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    insight_type: str = ""  # "alarm", "energy", "maintenance", "optimization"
    title: str = ""
    description: str = ""
    
    # Source
    source_equipment_ids: List[str] = field(default_factory=list)
    source_alarm_ids: List[str] = field(default_factory=list)
    source_anomaly_ids: List[str] = field(default_factory=list)
    
    # Priority and confidence
    priority: str = "medium"  # "critical", "high", "medium", "low"
    confidence: float = 0.0   # 0.0 - 1.0
    
    # Actionable
    recommended_action: str = ""
    estimated_impact: str = ""  # e.g., "Save QAR 15,000/year"
    
    # Lifecycle
    created_at: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False
    dismissed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "estimated_impact": self.estimated_impact,
            "created_at": self.created_at.isoformat(),
            "acknowledged": self.acknowledged,
        }
