"""
Mock Objects for Testing
========================

Deterministic, fast, free mocks for external dependencies.

Philosophy:
- Mock EXTERNAL dependencies (LLM, BACnet, network)
- TEST internal logic (business rules, algorithms)
- Keep mocks simple and configurable

"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.tests.mocks")


# ============================================================================
# MOCK LLM
# ============================================================================

class MockLLM:
    """
    Mock LLM with configurable responses.
    
    Usage:
        llm = MockLLM(responses={
            "status": '{"equipment": "running"}',
            "alarm": '{"severity": "critical"}',
        })
        
        result = await llm.ask("What is the status?")
        # Returns: '{"equipment": "running"}'
        
        # Simulate timeout
        llm.timeout_after(2.0)
        
        # Simulate rate limit
        llm.rate_limit()
        
        # Simulate garbage response
        llm.garbage_mode()
    """
    
    def __init__(
        self,
        responses: Optional[Dict[str, str]] = None,
        default_response: str = '{"status": "ok"}',
        latency_ms: float = 50.0,
    ):
        self.responses = responses or {}
        self.default_response = default_response
        self.latency_ms = latency_ms
        
        # Failure simulation
        self._timeout_after: Optional[float] = None
        self._rate_limit: bool = False
        self._garbage_mode: bool = False
        self._call_count: int = 0
        self._call_history: List[Dict[str, Any]] = []
    
    async def ask(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Simulate LLM call with configured response."""
        self._call_count += 1
        self._call_history.append({
            "prompt": prompt[:200],
            "timestamp": datetime.now().isoformat(),
            "kwargs": kwargs,
        })
        
        # Simulate latency
        await asyncio.sleep(self.latency_ms / 1000.0)
        
        # Simulate timeout
        if self._timeout_after is not None:
            await asyncio.sleep(self._timeout_after)
            raise asyncio.TimeoutError("LLM request timed out")
        
        # Simulate rate limit
        if self._rate_limit:
            raise Exception("Rate limit exceeded (429)")
        
        # Simulate garbage
        if self._garbage_mode:
            return "asdkjh123987!!@#$%^&*()"
        
        # Find matching response
        for keyword, response in self.responses.items():
            if keyword.lower() in prompt.lower():
                return response
        
        return self.default_response
    
    def set_response(self, keyword: str, response: str) -> None:
        """Add or update a response."""
        self.responses[keyword] = response
    
    def timeout_after(self, seconds: float) -> None:
        """Configure to timeout after N seconds."""
        self._timeout_after = seconds
    
    def rate_limit(self) -> None:
        """Configure to raise rate limit error."""
        self._rate_limit = True
    
    def garbage_mode(self, enabled: bool = True) -> None:
        """Configure to return garbage."""
        self._garbage_mode = enabled
    
    def reset(self) -> None:
        """Reset all failure simulation."""
        self._timeout_after = None
        self._rate_limit = False
        self._garbage_mode = False
    
    def get_call_count(self) -> int:
        """Return number of calls."""
        return self._call_count
    
    def get_call_history(self) -> List[Dict[str, Any]]:
        """Return call history."""
        return self._call_history


# ============================================================================
# MOCK BACNET ADAPTER
# ============================================================================

class MockBACnetAdapter:
    """
    Mock BACnet adapter with configurable equipment and data.
    
    Usage:
        adapter = MockBACnetAdapter()
        
        # Configure equipment
        adapter.add_device(1001, "Chiller-01", "192.168.1.101")
        adapter.add_point("CH-01/CHWST", 7.0, "°C", device_id=1001)
        
        # Read point
        value = await adapter.read_point("CH-01/CHWST")
        # Returns: {"point_id": "CH-01/CHWST", "value": 7.0, ...}
        
        # Simulate failure
        adapter.set_point_error("CH-01/CHWST", "Sensor offline")
    """
    
    def __init__(self):
        self.devices: Dict[int, Dict[str, Any]] = {}
        self.points: Dict[str, Dict[str, Any]] = {}
        self.point_errors: Dict[str, str] = {}
        self._is_connected: bool = False
        self._polling: bool = False
        self._call_count: int = 0
    
    # --- Connection ---
    
    async def connect(self) -> bool:
        """Simulate connection."""
        self._is_connected = True
        return True
    
    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._is_connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected
    
    # --- Device Management ---
    
    def add_device(
        self,
        device_id: int,
        name: str,
        address: str = "127.0.0.1",
        vendor: str = "Test Vendor",
    ) -> None:
        """Add a device to the mock."""
        self.devices[device_id] = {
            "device_id": device_id,
            "name": name,
            "address": address,
            "vendor": vendor,
        }
    
    def add_point(
        self,
        point_id: str,
        value: float,
        unit: str = "",
        device_id: int = 1001,
        equipment_id: str = "",
        name: str = "",
    ) -> None:
        """Add a point to the mock."""
        self.points[point_id] = {
            "point_id": point_id,
            "value": value,
            "unit": unit,
            "device_id": device_id,
            "equipment_id": equipment_id,
            "name": name or point_id,
            "timestamp": datetime.now().isoformat(),
        }
    
    def set_point_value(self, point_id: str, value: float) -> None:
        """Update a point's value."""
        if point_id in self.points:
            self.points[point_id]["value"] = value
            self.points[point_id]["timestamp"] = datetime.now().isoformat()
    
    def set_point_error(self, point_id: str, error: str) -> None:
        """Configure a point to return an error."""
        self.point_errors[point_id] = error
    
    # --- Read Operations ---
    
    async def read_point(self, point_id: str) -> Optional[Dict[str, Any]]:
        """Read a point's value."""
        self._call_count += 1
        
        # Simulate error
        if point_id in self.point_errors:
            raise Exception(self.point_errors[point_id])
        
        # Return point or None
        if point_id in self.points:
            point = self.points[point_id].copy()
            # Add realistic drift
            point["value"] = point["value"] + random.uniform(-0.1, 0.1)
            point["timestamp"] = datetime.now().isoformat()
            return point
        
        return None
    
    async def read_all_points(self) -> List[Dict[str, Any]]:
        """Read all points."""
        results = []
        for point_id in self.points:
            point = await self.read_point(point_id)
            if point:
                results.append(point)
        return results
    
    async def discover_devices(self) -> List[Dict[str, Any]]:
        """Return all configured devices."""
        return list(self.devices.values())
    
    # --- Polling ---
    
    def start_polling(self, interval_seconds: int = 60) -> None:
        """Start polling (mock: just set flag)."""
        self._polling = True
    
    def stop_polling(self) -> None:
        """Stop polling."""
        self._polling = False
    
    def get_stats(self) -> Dict[str, Any]:
        """Return mock stats."""
        return {
            "is_connected": self._is_connected,
            "devices": len(self.devices),
            "points": len(self.points),
            "polling": self._polling,
            "call_count": self._call_count,
        }


# ============================================================================
# MOCK BMS STATE ENGINE
# ============================================================================

class MockBMSStateEngine:
    """
    Mock BMS state engine with sample equipment and data.
    
    Usage:
        state = MockBMSStateEngine()
        
        # Add equipment
        state.add_equipment({"equipment_id": "CH-01", "name": "Chiller 1"})
        
        # Add data point
        state.update_point("CH-01/CHWST", 7.0)
        
        # Query
        equipment = state.get_equipment("CH-01")
        points = state.get_points_by_equipment("CH-01")
    """
    
    def __init__(self):
        self._equipment: Dict[str, Dict[str, Any]] = {}
        self._points: Dict[str, Dict[str, Any]] = {}
        self._point_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._alarms: List[Dict[str, Any]] = []
        self._callbacks: List[Callable] = []
    
    # --- Equipment ---
    
    def add_equipment(self, equipment: Dict[str, Any]) -> None:
        """Add equipment to the mock."""
        eq_id = equipment.get("equipment_id")
        if eq_id:
            self._equipment[eq_id] = equipment
    
    def get_equipment(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        """Get equipment by ID."""
        return self._equipment.get(equipment_id)
    
    def get_all_equipment(self) -> List[Dict[str, Any]]:
        """Get all equipment."""
        return list(self._equipment.values())
    
    # --- Points ---
    
    def update_point(
        self,
        point_id: str,
        value: float,
        unit: str = "",
        equipment_id: str = "",
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Update or add a point."""
        ts = timestamp or datetime.now()
        point = {
            "point_id": point_id,
            "value": value,
            "unit": unit,
            "equipment_id": equipment_id,
            "timestamp": ts.isoformat(),
        }
        self._points[point_id] = point
        self._point_history[point_id].append(point)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(point)
            except Exception as e:
                logger.warning(f"Callback error: {e}")
    
    def get_point(self, point_id: str) -> Optional[Dict[str, Any]]:
        """Get a point's current value."""
        return self._points.get(point_id)
    
    def get_points_by_equipment(self, equipment_id: str) -> List[Dict[str, Any]]:
        """Get all points for equipment."""
        return [
            p for p in self._points.values()
            if p.get("equipment_id") == equipment_id
        ]
    
    def get_point_history(
        self,
        point_id: str,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Get point history."""
        cutoff = datetime.now() - timedelta(hours=hours)
        history = self._point_history.get(point_id, [])
        return [
            p for p in history
            if datetime.fromisoformat(p["timestamp"]) >= cutoff
        ]
    
    # --- Alarms ---
    
    def add_alarm(self, alarm: Dict[str, Any]) -> None:
        """Add an alarm."""
        alarm.setdefault("alarm_id", f"ALM-{len(self._alarms) + 1}")
        alarm.setdefault("timestamp", datetime.now().isoformat())
        self._alarms.append(alarm)
    
    def get_active_alarms(self) -> List[Dict[str, Any]]:
        """Get active alarms."""
        return [a for a in self._alarms if a.get("status") != "acknowledged"]
    
    def acknowledge_alarm(self, alarm_id: str) -> bool:
        """Acknowledge an alarm."""
        for alarm in self._alarms:
            if alarm.get("alarm_id") == alarm_id:
                alarm["status"] = "acknowledged"
                return True
        return False
    
    # --- Callbacks ---
    
    def on_point_update(self, callback: Callable) -> None:
        """Register callback for point updates."""
        self._callbacks.append(callback)
    
    # --- State ---
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of current state."""
        return {
            "equipment_count": len(self._equipment),
            "point_count": len(self._points),
            "active_alarms": len(self.get_active_alarms()),
            "total_alarms": len(self._alarms),
        }
    
    def clear(self) -> None:
        """Clear all state."""
        self._equipment.clear()
        self._points.clear()
        self._point_history.clear()
        self._alarms.clear()
    
    # --- Zones ---
    
    def add_zone(self, zone: Dict[str, Any]) -> None:
        """Add a zone for ghost detection."""
        zone_id = zone.get("zone_id")
        if zone_id:
            if not hasattr(self, '_zones'):
                self._zones = {}
            self._zones[zone_id] = zone
    
    def get_all_zones(self) -> List[Dict[str, Any]]:
        """Get all zones."""
        return list(getattr(self, '_zones', {}).values())
    
    async def get_zone_with_current_values(self, zone_id: str) -> Optional[Dict[str, Any]]:
        """Get zone with current sensor values."""
        zones = getattr(self, '_zones', {})
        zone = zones.get(zone_id)
        if zone:
            zone_data = zone.copy()
            zone_data["co2_ppm"] = zone.get("co2_ppm")
            zone_data["vav_damper_pct"] = zone.get("vav_damper_pct")
            zone_data["light_status"] = zone.get("light_status")
            zone_data["load_kw"] = zone.get("load_kw", 2.0)
            return zone_data
        return None
    
    # --- Energy ---
    
    def add_energy_reading(self, reading: Dict[str, Any]) -> None:
        """Add an energy reading."""
        if not hasattr(self, '_energy_readings'):
            self._energy_readings = []
        self._energy_readings.append(reading)
    
    def get_energy_readings(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get energy readings."""
        readings = getattr(self, '_energy_readings', [])
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            r for r in readings
            if datetime.fromisoformat(r.get("timestamp", datetime.now().isoformat())) >= cutoff
        ]


# ============================================================================
# MOCK DATABASE
# ============================================================================

class MockDatabase:
    """
    In-memory SQLite database for testing.
    
    Usage:
        db = MockDatabase()
        await db.save_data_point("CH-01/CHWST", 7.0)
        history = await db.get_point_history("CH-01/CHWST", hours=24)
    """
    
    def __init__(self):
        self._data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._is_closed: bool = False
    
    async def save_data_point(
        self,
        point_id: str,
        value: float,
        unit: str = "",
        equipment_id: str = "",
    ) -> None:
        """Save a data point."""
        self._data[point_id].append({
            "point_id": point_id,
            "value": value,
            "unit": unit,
            "equipment_id": equipment_id,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def get_point_history(
        self,
        point_id: str,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Get point history."""
        cutoff = datetime.now() - timedelta(hours=hours)
        history = self._data.get(point_id, [])
        return [
            p for p in history
            if datetime.fromisoformat(p["timestamp"]) >= cutoff
        ]
    
    async def close(self) -> None:
        """Close database."""
        self._is_closed = True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database stats."""
        total_points = sum(len(points) for points in self._data.values())
        return {
            "unique_points": len(self._data),
            "total_readings": total_points,
            "is_closed": self._is_closed,
        }


# ============================================================================
# MOCK ENERGY ANALYZER
# ============================================================================

class MockEnergyAnalyzer:
    """
    Mock energy analyzer for testing.
    
    Usage:
        analyzer = MockEnergyAnalyzer(total_kwh=500)
        analyzer.add_waste_pattern({"pattern_type": "ghost_operation", "estimated_savings_qar": 50})
        
        summary = analyzer.get_summary()
        patterns = analyzer.identify_waste_patterns()
    """
    
    def __init__(
        self,
        total_kwh: float = 500.0,
        cost_qar: float = 75.0,
        anomalies: Optional[List[Dict[str, Any]]] = None,
    ):
        self._total_kwh = total_kwh
        self._cost_qar = cost_qar
        self._anomalies = anomalies or []
        self._waste_patterns: List[Dict[str, Any]] = []
    
    def get_summary(self) -> Dict[str, Any]:
        """Get energy summary."""
        return {
            "total_kwh": self._total_kwh,
            "cost_qar": self._cost_qar,
            "anomalies": self._anomalies,
            "baseline_kwh": self._total_kwh * 0.95,
            "savings_potential_qar": self._cost_qar * 0.1,
        }
    
    def identify_waste_patterns(self) -> List[Dict[str, Any]]:
        """Get waste patterns."""
        return self._waste_patterns
    
    def add_waste_pattern(self, pattern: Dict[str, Any]) -> None:
        """Add a waste pattern."""
        self._waste_patterns.append(pattern)
    
    def clear_patterns(self) -> None:
        """Clear all patterns."""
        self._waste_patterns.clear()


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def create_mock_llm_with_responses(responses: Dict[str, str]) -> MockLLM:
    """Create MockLLM with specific responses."""
    return MockLLM(responses=responses)


def create_mock_bacnet_with_equipment(
    chillers: int = 1,
    ahus: int = 2,
    meters: int = 1,
) -> MockBACnetAdapter:
    """Create MockBACnetAdapter with sample equipment."""
    adapter = MockBACnetAdapter()
    
    # Add chillers
    for i in range(1, chillers + 1):
        adapter.add_device(1000 + i, f"Chiller-{i:02d}", f"192.168.1.{100 + i}")
        adapter.add_point(f"CH-{i:02d}/CHWST", 7.0, "°C", device_id=1000 + i)
        adapter.add_point(f"CH-{i:02d}/CHWRT", 12.0, "°C", device_id=1000 + i)
        adapter.add_point(f"CH-{i:02d}/KW", 250.0, "kW", device_id=1000 + i)
    
    # Add AHUs
    for i in range(1, ahus + 1):
        adapter.add_device(2000 + i, f"AHU-{i:02d}", f"192.168.1.{200 + i}")
        adapter.add_point(f"AHU-{i:02d}/SAT", 14.0, "°C", device_id=2000 + i)
        adapter.add_point(f"AHU-{i:02d}/RAT", 24.0, "°C", device_id=2000 + i)
    
    # Add meters
    for i in range(1, meters + 1):
        adapter.add_device(5000 + i, f"Meter-{i:02d}", f"192.168.1.{500 + i}")
        adapter.add_point(f"METER-{i:02d}/KW", 450.0, "kW", device_id=5000 + i)
    
    return adapter


def create_mock_bms_state_with_equipment() -> MockBMSStateEngine:
    """Create MockBMSStateEngine with sample equipment."""
    state = MockBMSStateEngine()
    
    # Add chiller
    state.add_equipment({
        "equipment_id": "CH-01",
        "name": "Chiller 1",
        "equipment_type": "chiller",
        "status": "running",
        "location": "Central Plant",
    })
    
    # Add AHU
    state.add_equipment({
        "equipment_id": "AHU-01",
        "name": "Air Handler 1",
        "equipment_type": "ahu",
        "status": "running",
        "location": "Floor 1 Core",
    })
    
    # Add points
    state.update_point("CH-01/CHWST", 7.0, "°C", "CH-01")
    state.update_point("CH-01/CHWRT", 12.0, "°C", "CH-01")
    state.update_point("CH-01/KW", 250.0, "kW", "CH-01")
    state.update_point("AHU-01/SAT", 14.0, "°C", "AHU-01")
    state.update_point("AHU-01/RAT", 24.0, "°C", "AHU-01")
    state.update_point("METER-01/KW", 450.0, "kW", "METER-01")
    
    return state


# ============================================================================
# MOCK GSAS REPORTER
# ============================================================================

class MockGSASReporter:
    """
    Mock GSAS reporter for testing.
    
    Usage:
        reporter = MockGSASReporter(overall_score=78.5, target_score=85.0)
        reporter.add_improvement({"action": "Optimize chillers", "impact": 1.5})
        
        status = reporter.get_status()
        priorities = reporter.get_improvement_priorities()
    """
    
    def __init__(
        self,
        overall_score: float = 78.5,
        target_score: float = 85.0,
        certification_level: str = "3-Star",
        category_scores: Optional[Dict[str, float]] = None,
    ):
        self._overall_score = overall_score
        self._target_score = target_score
        self._certification_level = certification_level
        self._category_scores = category_scores or {
            "energy": 80.0,
            "water": 75.0,
            "indoor_environment": 82.0,
        }
        self._improvements: List[Dict[str, Any]] = []
    
    def get_status(self) -> Dict[str, Any]:
        """Get GSAS status."""
        return {
            "overall_score": self._overall_score,
            "certification_level": self._certification_level,
            "target_score": self._target_score,
            "gap_to_target": self._target_score - self._overall_score,
            "categories": self._category_scores,
        }
    
    def target_score(self) -> float:
        """Get target score."""
        return self._target_score
    
    def get_improvement_priorities(self) -> List[Dict[str, Any]]:
        """Get improvement priorities."""
        return self._improvements
    
    def add_improvement(self, improvement: Dict[str, Any]) -> None:
        """Add an improvement action."""
        self._improvements.append(improvement)
    
    def optimize_recommendations_for_targets(
        self,
        recommendations: List[Dict[str, Any]],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Score and rank recommendations by GSAS impact."""
        scored = []
        for rec in recommendations:
            # Score by potential GSAS impact
            gsas_aligned = rec.get("gsas_aligned", False)
            impact = rec.get("impact_estimate", {}).get("gsas_points", 0.0)
            
            score = impact * 2.0 if gsas_aligned else impact
            scored.append({**rec, "gsas_score": score})
        
        # Sort by GSAS score descending
        scored.sort(key=lambda x: x.get("gsas_score", 0), reverse=True)
        
        return scored[:limit]
    
    def clear_improvements(self) -> None:
        """Clear all improvements."""
        self._improvements.clear()
