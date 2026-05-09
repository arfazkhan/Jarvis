"""
Test Data Factories
==================

Easy generation of realistic test data.
All factories return dictionaries that can be used directly or converted to dataclasses.

Usage:
    from tests.factories import EquipmentFactory, AlarmFactory
    
    chiller = EquipmentFactory.chiller()
    critical_alarm = AlarmFactory.critical_chiller()
    
    # Customize
    chiller = EquipmentFactory.chiller(equipment_id="CH-99", status="fault")

"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ============================================================================
# EQUIPMENT FACTORY
# ============================================================================

class EquipmentFactory:
    """Generate equipment test data."""
    
    @staticmethod
    def chiller(
        equipment_id: str = "CH-01",
        name: str = "Chiller 1",
        status: str = "running",
        location: str = "Central Plant",
        capacity_tr: float = 1200.0,
        runtime_hours: float = 4523.5,
        efficiency: float = 0.94,
        active_alarms: int = 0,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a chiller equipment dict."""
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "chiller",
            "status": status,
            "location": location,
            "capacity_tr": capacity_tr,
            "runtime_hours": runtime_hours,
            "efficiency": efficiency,
            "active_alarms": active_alarms,
            **kwargs
        }
    
    @staticmethod
    def ahu(
        equipment_id: str = "AHU-01",
        name: str = "Air Handler 1",
        status: str = "running",
        location: str = "Floor 1 Core",
        design_cfm: float = 20000.0,
        runtime_hours: float = 3892.0,
        efficiency: float = 0.91,
        active_alarms: int = 0,
        **kwargs
    ) -> Dict[str, Any]:
        """Create an AHU equipment dict."""
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "ahu",
            "status": status,
            "location": location,
            "design_cfm": design_cfm,
            "runtime_hours": runtime_hours,
            "efficiency": efficiency,
            "active_alarms": active_alarms,
            **kwargs
        }
    
    @staticmethod
    def cooling_tower(
        equipment_id: str = "CT-01",
        name: str = "Cooling Tower 1",
        status: str = "running",
        location: str = "Roof",
        capacity_tr: float = 1500.0,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a cooling tower equipment dict."""
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "cooling_tower",
            "status": status,
            "location": location,
            "capacity_tr": capacity_tr,
            **kwargs
        }
    
    @staticmethod
    def meter(
        equipment_id: str = "METER-01",
        name: str = "Main Electric Meter",
        location: str = "Main Distribution Panel",
        **kwargs
    ) -> Dict[str, Any]:
        """Create an electric meter equipment dict."""
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "meter_electric",
            "status": "online",
            "location": location,
            **kwargs
        }
    
    @staticmethod
    def pump(
        equipment_id: str = "PUMP-01",
        name: str = "Chilled Water Pump 1",
        status: str = "running",
        location: str = "Central Plant",
        **kwargs
    ) -> Dict[str, Any]:
        """Create a pump equipment dict."""
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "pump",
            "status": status,
            "location": location,
            **kwargs
        }
    
    @staticmethod
    def random_chiller() -> Dict[str, Any]:
        """Create a random chiller."""
        num = random.randint(1, 99)
        return EquipmentFactory.chiller(
            equipment_id=f"CH-{num:02d}",
            name=f"Chiller {num}",
            status=random.choice(["running", "standby", "fault"]),
            efficiency=round(random.uniform(0.85, 0.98), 2),
            runtime_hours=round(random.uniform(1000, 10000), 1),
        )
    
    @staticmethod
    def random_ahu() -> Dict[str, Any]:
        """Create a random AHU."""
        num = random.randint(1, 99)
        return EquipmentFactory.ahu(
            equipment_id=f"AHU-{num:02d}",
            name=f"Air Handler {num}",
            status=random.choice(["running", "standby", "fault"]),
            efficiency=round(random.uniform(0.80, 0.95), 2),
        )
    
    @staticmethod
    def fleet(chillers: int = 2, ahus: int = 4) -> List[Dict[str, Any]]:
        """Create a fleet of equipment."""
        equipment = []
        for i in range(1, chillers + 1):
            equipment.append(EquipmentFactory.chiller(equipment_id=f"CH-{i:02d}"))
        for i in range(1, ahus + 1):
            equipment.append(EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}"))
        equipment.append(EquipmentFactory.meter())
        return equipment


# ============================================================================
# DATA POINT FACTORY
# ============================================================================

class DataPointFactory:
    """Generate data point test data."""
    
    @staticmethod
    def chiller_supply_temp(
        point_id: str = "CH-01/CHWST",
        value: float = 7.0,
        equipment_id: str = "CH-01",
    ) -> Dict[str, Any]:
        """Create a chiller supply temp point."""
        return {
            "point_id": point_id,
            "name": "Chilled Water Supply Temperature",
            "value": value,
            "unit": "°C",
            "equipment_id": equipment_id,
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def chiller_return_temp(
        point_id: str = "CH-01/CHWRT",
        value: float = 12.0,
        equipment_id: str = "CH-01",
    ) -> Dict[str, Any]:
        """Create a chiller return temp point."""
        return {
            "point_id": point_id,
            "name": "Chilled Water Return Temperature",
            "value": value,
            "unit": "°C",
            "equipment_id": equipment_id,
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def chiller_power(
        point_id: str = "CH-01/KW",
        value: float = 250.0,
        equipment_id: str = "CH-01",
    ) -> Dict[str, Any]:
        """Create a chiller power point."""
        return {
            "point_id": point_id,
            "name": "Chiller Power",
            "value": value,
            "unit": "kW",
            "equipment_id": equipment_id,
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def ahu_supply_temp(
        point_id: str = "AHU-01/SAT",
        value: float = 14.0,
        equipment_id: str = "AHU-01",
    ) -> Dict[str, Any]:
        """Create an AHU supply temp point."""
        return {
            "point_id": point_id,
            "name": "Supply Air Temperature",
            "value": value,
            "unit": "°C",
            "equipment_id": equipment_id,
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def building_power(
        point_id: str = "METER-01/KW",
        value: float = 450.0,
    ) -> Dict[str, Any]:
        """Create a building power point."""
        return {
            "point_id": point_id,
            "name": "Building Total Power",
            "value": value,
            "unit": "kW",
            "equipment_id": "METER-01",
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def random_point(equipment_id: str = "CH-01") -> Dict[str, Any]:
        """Create a random data point."""
        point_types = [
            ("SAT", "Supply Air Temperature", "°C", 10, 20),
            ("RAT", "Return Air Temperature", "°C", 20, 30),
            ("KW", "Power", "kW", 100, 500),
            ("FLOW", "Flow Rate", "L/s", 50, 200),
            ("PRESS", "Pressure", "kPa", 100, 500),
        ]
        suffix, name, unit, min_val, max_val = random.choice(point_types)
        return {
            "point_id": f"{equipment_id}/{suffix}",
            "name": name,
            "value": round(random.uniform(min_val, max_val), 2),
            "unit": unit,
            "equipment_id": equipment_id,
            "point_type": "sensor",
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================================
# ALARM FACTORY
# ============================================================================

class AlarmFactory:
    """Generate alarm test data."""
    
    @staticmethod
    def critical_chiller(
        alarm_id: str = None,
        equipment_id: str = "CH-01",
        message: str = "Chiller high discharge pressure",
    ) -> Dict[str, Any]:
        """Create a critical chiller alarm."""
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": message,
            "severity": "critical",
            "status": "active",
            "timestamp": datetime.now().isoformat(),
            "acknowledged_by": None,
            "acknowledged_at": None,
        }
    
    @staticmethod
    def warning_ahu(
        alarm_id: str = None,
        equipment_id: str = "AHU-01",
        message: str = "AHU filter differential pressure high",
    ) -> Dict[str, Any]:
        """Create a warning AHU alarm."""
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": message,
            "severity": "warning",
            "status": "active",
            "timestamp": datetime.now().isoformat(),
            "acknowledged_by": None,
            "acknowledged_at": None,
        }
    
    @staticmethod
    def info_zone(
        alarm_id: str = None,
        equipment_id: str = "ZONE-01",
        message: str = "Zone temperature slightly above setpoint",
    ) -> Dict[str, Any]:
        """Create an info zone alarm."""
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": message,
            "severity": "info",
            "status": "active",
            "timestamp": datetime.now().isoformat(),
            "acknowledged_by": None,
            "acknowledged_at": None,
        }
    
    @staticmethod
    def flood(count: int = 100) -> List[Dict[str, Any]]:
        """Generate a large number of alarms."""
        return [
            AlarmFactory.warning_ahu(
                alarm_id=f"FLOOD-{i:04d}",
                message=f"Flood alarm {i}"
            )
            for i in range(count)
        ]
    
    @staticmethod
    def cascade(count: int = 5, root_equipment: str = "CH-01") -> List[Dict[str, Any]]:
        """Generate a cascade of related alarms."""
        cluster_id = f"CL-{uuid.uuid4().hex[:6]}"
        root = AlarmFactory.critical_chiller(
            alarm_id=f"ROOT-{uuid.uuid4().hex[:6]}",
            equipment_id=root_equipment
        )
        root["cluster_id"] = cluster_id
        
        related = [
            AlarmFactory.warning_ahu(
                alarm_id=f"REL-{i:03d}",
                equipment_id=f"VAV-{i:02d}"
            )
            for i in range(count - 1)
        ]
        for r in related:
            r["cluster_id"] = cluster_id
            
        return [root] + related
    
    @staticmethod
    def acknowledged(
        alarm_id: str = None,
        equipment_id: str = "AHU-02",
        message: str = "Previously acknowledged alarm",
    ) -> Dict[str, Any]:
        """Create an acknowledged alarm."""
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": message,
            "severity": "warning",
            "status": "acknowledged",
            "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
            "acknowledged_by": "operator@example.com",
            "acknowledged_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        }
    
    @staticmethod
    def random_alarm() -> Dict[str, Any]:
        """Create a random alarm."""
        severity = random.choice(["critical", "warning", "info"])
        equipment_types = [("CH", "Chiller"), ("AHU", "Air Handler"), ("ZONE", "Zone")]
        prefix, eq_type = random.choice(equipment_types)
        
        messages = {
            "critical": [f"{eq_type} critical fault", f"{eq_type} safety trip", f"{eq_type} emergency shutdown"],
            "warning": [f"{eq_type} approaching limit", f"{eq_type} degraded performance", f"{eq_type} needs attention"],
            "info": [f"{eq_type} informational event", f"{eq_type} status change", f"{eq_type} routine notification"],
        }
        
        return {
            "alarm_id": f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": f"{prefix}-{random.randint(1, 99):02d}",
            "message": random.choice(messages[severity]),
            "severity": severity,
            "status": random.choice(["active", "acknowledged"]),
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def flood(count: int = 100) -> List[Dict[str, Any]]:
        """Create a flood of alarms for stress testing."""
        return [AlarmFactory.random_alarm() for _ in range(count)]


# ============================================================================
# ENERGY READING FACTORY
# ============================================================================

class EnergyReadingFactory:
    """Generate energy reading test data."""
    
    @staticmethod
    def current(
        reading_id: str = None,
        building_id: str = "BUILDING-01",
        total_kw: float = 450.0,
        hvac_kw: float = 350.0,
        lighting_kw: float = 50.0,
        other_kw: float = 50.0,
    ) -> Dict[str, Any]:
        """Create a current energy reading."""
        return {
            "reading_id": reading_id or f"RDG-{uuid.uuid4().hex[:8]}",
            "building_id": building_id,
            "timestamp": datetime.now().isoformat(),
            "total_kw": total_kw,
            "hvac_kw": hvac_kw,
            "lighting_kw": lighting_kw,
            "other_kw": other_kw,
        }
    
    @staticmethod
    def reading(hour_offset: int = 0, kw: float = 450.0) -> Dict[str, Any]:
        """Create a reading with an hour offset from now."""
        timestamp = datetime.now() - timedelta(hours=hour_offset)
        return EnergyReadingFactory.at_time(timestamp, kw)
    
    @staticmethod
    def at_time(
        timestamp: datetime,
        total_kw: float = 450.0,
        building_id: str = "BUILDING-01",
    ) -> Dict[str, Any]:
        """Create an energy reading at a specific time."""
        return {
            "reading_id": f"RDG-{uuid.uuid4().hex[:8]}",
            "building_id": building_id,
            "timestamp": timestamp.isoformat(),
            "total_kw": total_kw,
            "hvac_kw": total_kw * 0.75,
            "lighting_kw": total_kw * 0.15,
            "other_kw": total_kw * 0.10,
        }
    
    @staticmethod
    def last_24_hours(
        building_id: str = "BUILDING-01",
        base_kw: float = 450.0,
        variance: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Create 24 hours of energy readings."""
        readings = []
        for hour in range(24):
            timestamp = datetime.now() - timedelta(hours=23 - hour)
            # Simulate daily load pattern
            if 6 <= timestamp.hour <= 18:  # Daytime
                kw = base_kw + variance * 0.5
            else:  # Nighttime
                kw = base_kw - variance * 0.5
            kw += random.uniform(-variance * 0.2, variance * 0.2)
            readings.append(EnergyReadingFactory.at_time(timestamp, round(kw, 2), building_id))
        return readings
    
    @staticmethod
    def last_week(
        building_id: str = "BUILDING-01",
    ) -> List[Dict[str, Any]]:
        """Create 7 days of hourly readings."""
        readings = []
        for day in range(7):
            for hour in range(24):
                timestamp = datetime.now() - timedelta(days=6 - day, hours=hour)
                # Weekday vs weekend pattern
                if timestamp.weekday() < 5:  # Weekday
                    if 8 <= timestamp.hour <= 18:
                        kw = 450 + random.uniform(-30, 30)
                    else:
                        kw = 250 + random.uniform(-20, 20)
                else:  # Weekend
                    kw = 200 + random.uniform(-30, 30)
                readings.append(EnergyReadingFactory.at_time(timestamp, round(kw, 2), building_id))
        return readings


# ============================================================================
# GSAS CRITERION FACTORY
# ============================================================================

class GSASFactory:
    """Generate GSAS criterion test data."""
    
    @staticmethod
    def criterion(
        criterion_id: str = "E.1",
        name: str = "Energy Demand Performance",
        category: str = "E",
        max_points: float = 3.0,
        current_points: float = 0.0,
        status: str = "not_started",
    ) -> Dict[str, Any]:
        """Create a GSAS criterion."""
        return {
            "criterion_id": criterion_id,
            "name": name,
            "category": category,
            "max_points": max_points,
            "current_points": current_points,
            "status": status,
            "is_bms_measurable": True,
        }
    
    @staticmethod
    def energy_criteria() -> List[Dict[str, Any]]:
        """Create energy category criteria."""
        return [
            GSASFactory.criterion("E.1", "Energy Demand Performance", "E", 3.0, 1.5, "in_progress"),
            GSASFactory.criterion("E.2", "Energy Efficiency Performance", "E", 3.0, 2.0, "in_progress"),
            GSASFactory.criterion("E.3", "Renewable Energy", "E", 3.0, 0.0, "not_started"),
            GSASFactory.criterion("E.4", "Energy Monitoring", "E", 2.0, 2.0, "achieved"),
        ]
    
    @staticmethod
    def water_criteria() -> List[Dict[str, Any]]:
        """Create water category criteria."""
        return [
            GSASFactory.criterion("W.1", "Water Demand Performance", "W", 3.0, 1.0, "in_progress"),
            GSASFactory.criterion("W.2", "Water Efficiency Performance", "W", 3.0, 1.5, "in_progress"),
            GSASFactory.criterion("W.3", "Water Reuse", "W", 2.0, 0.0, "not_started"),
        ]


# ============================================================================
# RECOMMENDATION FACTORY
# ============================================================================

class RecommendationFactory:
    """Generate recommendation test data."""
    
    @staticmethod
    def energy_optimization(
        recommendation_id: str = None,
        equipment_id: str = "AHU-01",
        action: str = "reduce_cooling_setpoint",
        confidence: float = 0.85,
        estimated_savings_kwh: float = 150.0,
        gsas_aligned: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Create an energy optimization recommendation."""
        return {
            "recommendation_id": recommendation_id or f"REC-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "action": action,
            "confidence": confidence,
            "gsas_aligned": gsas_aligned,
            "gsas_category": "E",
            "estimated_savings_kwh": estimated_savings_kwh,
            "priority": "medium",
            "created_at": datetime.now().isoformat(),
            **kwargs
        }
    
    @staticmethod
    def maintenance_alert(
        recommendation_id: str = None,
        equipment_id: str = "CH-01",
        action: str = "schedule_compressor_maintenance",
        confidence: float = 0.92,
        days_until_failure: int = 14,
        gsas_aligned: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a maintenance recommendation."""
        return {
            "recommendation_id": recommendation_id or f"REC-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "action": action,
            "confidence": confidence,
            "gsas_aligned": gsas_aligned,
            "gsas_category": "MO",
            "days_until_failure": days_until_failure,
            "priority": "high",
            "created_at": datetime.now().isoformat(),
            **kwargs
        }
    
    @staticmethod
    def gsas_improvement(
        recommendation_id: str = None,
        criterion_id: str = "E.1",
        action: str = "optimize_chiller_sequence",
        current_score: float = 1.5,
        target_score: float = 3.0,
    ) -> Dict[str, Any]:
        """Create a GSAS improvement recommendation."""
        return {
            "recommendation_id": recommendation_id or f"REC-{uuid.uuid4().hex[:8]}",
            "criterion_id": criterion_id,
            "action": action,
            "current_score": current_score,
            "target_score": target_score,
            "confidence": 0.88,
            "gsas_aligned": True,
            "priority": "high",
            "created_at": datetime.now().isoformat(),
        }
    @staticmethod
    def reduce_setpoint(**kwargs) -> Dict[str, Any]:
        """Alias for reduce_cooling_setpoint."""
        return RecommendationFactory.reduce_cooling_setpoint(**kwargs)

    @staticmethod
    def reduce_cooling_setpoint(**kwargs) -> Dict[str, Any]:
        """Create a cooling setpoint reduction recommendation."""
        return RecommendationFactory.energy_optimization(action="reduce_cooling_setpoint", **kwargs)
    
    @staticmethod
    def schedule_maintenance(**kwargs) -> Dict[str, Any]:
        """Create a general maintenance recommendation."""
        return RecommendationFactory.maintenance_alert(action="schedule_maintenance", **kwargs)
