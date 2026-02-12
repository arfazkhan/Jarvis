"""
Mocks for BMS Battle Testing
============================

Mock classes to simulate BMS engines and data structures
for end-to-end tool testing.
"""

from typing import List, Optional, Any, Dict
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel

# --- Data Models ---

class MockEnum(Enum):
    def __str__(self):
        return self.value

class EquipmentType(MockEnum):
    AHU = "air_handling_unit"
    CHILLER = "chiller"
    VAV = "vav"
    FCU = "fcu"
    PUMP = "pump"

class EquipmentStatus(MockEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAULT = "fault"
    MAINTENANCE = "maintenance"

class AlarmSeverity(MockEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class AlarmState(MockEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"

class MockPoint(BaseModel):
    point_id: str
    name: str
    value: Any
    unit: str

class MockEquipment:
    def __init__(self, id, name, type_, status, location):
        self.equipment_id = id
        self.name = name
        self.eq_type = type_
        self.status = status
        self.location = location

class MockAlarm:
    def __init__(self, id, eq_id, msg, sev, state, time):
        self.alarm_id = id
        self.equipment_id = eq_id
        self.message = msg
        self.severity = sev
        self.state = state
        self.triggered_at = time

# --- Mock Engines ---

class MockBMSState:
    def __init__(self):
        # Sample Data
        self.equipment = [
            MockEquipment("CH-01", "Chiller 1", EquipmentType.CHILLER, EquipmentStatus.RUNNING, "Basement"),
            MockEquipment("AHU-01", "AHU Level 1", EquipmentType.AHU, EquipmentStatus.FAULT, "Roof"),
            MockEquipment("VAV-101", "Zone 101 VAV", EquipmentType.VAV, EquipmentStatus.RUNNING, "Floor 1"),
        ]
        
        self.points = {
            "CH-01": [
                MockPoint(point_id="CH01_SAPT", name="Supply Temp", value=7.2, unit="C"),
                MockPoint(point_id="CH01_RETT", name="Return Temp", value=12.5, unit="C"),
                MockPoint(point_id="CH01_POWR", name="Power", value=145.5, unit="kW"),
            ],
            "AHU-01": [
                MockPoint(point_id="AHU01_SAPT", name="Supply Temp", value=22.0, unit="C"),
                MockPoint(point_id="AHU01_FAN", name="Fan Speed", value=0, unit="%"),
            ]
        }
        
    def get_equipment_sync(self, eq_id: str):
        return next((e for e in self.equipment if e.equipment_id == eq_id), None)
        
    def get_all_equipment(self):
        return self.equipment
        
    def get_points_by_equipment(self, eq_id: str):
        return self.points.get(eq_id, [])
        
    def get_alarms_by_equipment(self, eq_id: str):
        # Delegate to alarm engine logic simulation
        return [a for a in MockAlarmEngine().get_active_alarms() if a.equipment_id == eq_id]

class MockAlarmEngine:
    def __init__(self):
        self.alarms = [
            MockAlarm("ALM-001", "AHU-01", "Fan Failure", AlarmSeverity.CRITICAL, AlarmState.ACTIVE, datetime.now()),
            MockAlarm("ALM-002", "CH-01", "High Return Temp", AlarmSeverity.MEDIUM, AlarmState.ACTIVE, datetime.now()),
        ]
        
    def get_active_alarms(self):
        return self.alarms
        
    def acknowledge_alarm(self, alarm_id, by=None):
        for a in self.alarms:
            if a.alarm_id == alarm_id:
                a.state = AlarmState.ACKNOWLEDGED
                return True
        return False

class MockEnergyAnalyzer:
    def get_consumption(self, **kwargs):
        return {"total_kwh": 5432.1, "cost": 1200.5, "breakdown": {"hvac": 60, "lighting": 30}}
        
    def detect_anomalies(self, **kwargs):
        return [{"id": "ANOM-01", "description": "High baseline load", "severity": "medium"}]
    
    def calculate_cost_impact(self, **kwargs):
        return {"daily_cost": 450.0, "projected_monthly": 13500.0}
        
    def get_burn_rate(self, **kwargs):
        return {"current_burn_rate": 150.0, "budget_status": "on_track"}

class MockGSASReporter:
    def get_score(self):
        return {"score": 2.5, "cert_level": "Bronze"}
    
    def get_improvements(self):
        return [{"category": "Energy", "action": "Optimize scheduling", "impact": "High"}]
    
    def generate_report(self):
        return {"report_url": "http://simulated/report.pdf", "generated_at": str(datetime.now())}

class MockSkillbook:
    def query_skills(self, **kwargs):
        return []
    
    def add_skill(self, **kwargs):
        return "SKILL-123"

class MockMLEngine:
    def forecast(self, **kwargs):
        return {"forecast": [100, 110, 105], "confidence": 0.9}
    
    def detect_faults(self, **kwargs):
        return [{"id": "FAULT-X", "probability": 0.85, "component": "Compressor"}]
        
    def analyze_root_cause(self, **kwargs):
        return {"cause": "Sensor drift", "probability": 0.92}
        
    def simulate(self, **kwargs):
        return {"outcome": "Energy savings of 5%", "risk": "Low"}
        
    def benchmark(self, **kwargs):
        return {"efficiency_percentile": 75, "comparison": "Better than average"}

class MockBriefingEngine:
    def generate_briefing(self, **kwargs):
        return "Morning Briefing:\n- System Status: Nominal\n- Active Alarms: 2\n- Efficiency: 92%"
