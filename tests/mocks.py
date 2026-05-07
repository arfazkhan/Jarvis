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
# MOCK DATA CLASS HELPERS
# ============================================================================

class MockEquipment:
    """Mock equipment object with to_dict() method."""
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
        # Set attributes
        for key, value in data.items():
            setattr(self, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


class MockDataPoint:
    """Mock data point object with to_dict() method."""
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
        for key, value in data.items():
            setattr(self, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


class MockAlarm:
    """Mock alarm object with to_dict() method."""
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
        for key, value in data.items():
            setattr(self, key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


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
    
    async def get_equipment(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        """Get equipment by ID."""
        data = self._equipment.get(equipment_id)
        return MockEquipment(data) if data else None
    
    async def get_all_equipment(self) -> List[Dict[str, Any]]:
        """Get all equipment."""
        return [MockEquipment(data) for data in self._equipment.values()]
    
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
    
    async def get_point(self, point_id: str) -> Optional[Dict[str, Any]]:
        """Get a point's current value."""
        return self._points.get(point_id)
    
    async def get_points_by_equipment(self, equipment_id: str) -> List[Dict[str, Any]]:
        """Get all points for equipment."""
        return [
            p for p in self._points.values()
            if p.get("equipment_id") == equipment_id
        ]
    
    async def get_point_history(
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
    
    async def get_active_alarms(self) -> List[Dict[str, Any]]:
        """Get active alarms."""
        return [a for a in self._alarms if a.get("status") != "acknowledged"]
    
    async def acknowledge_alarm(self, alarm_id: str) -> bool:
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


# ============================================================================
# MOCK ADVISOR
# ============================================================================

class MockAdvisor:
    """Mock advisor for testing recommendations."""
    
    def __init__(
        self,
        recommendations: Optional[List[Dict[str, Any]]] = None,
    ):
        self._recommendations = recommendations or []
        self._call_count = 0
    
    async def get_recommendations(
        self,
        context: str,
        equipment_id: Optional[str] = None,
        alarm_id: Optional[str] = None,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        self._call_count += 1
        return {
            "context": context,
            "recommendations": self._recommendations[:top_k],
        }
    
    def set_recommendations(self, recommendations: List[Dict[str, Any]]) -> None:
        self._recommendations = recommendations


# ============================================================================
# MOCK GOAL GENERATOR
# ============================================================================

class MockGoalGenerator:
    """Mock goal generator for testing."""
    
    def __init__(self, goals: Optional[List[Dict[str, Any]]] = None):
        self._goals = goals or []
        self._call_count = 0
    
    def get_active_goals(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        self._call_count += 1
        if category:
            return [g for g in self._goals if g.get("category") == category]
        return self._goals
    
    def add_goal(self, goal: Dict[str, Any]) -> None:
        self._goals.append(goal)


# ============================================================================
# MOCK BRIEFING SCHEDULER
# ============================================================================

class MockBriefingScheduler:
    """Mock briefing scheduler for testing."""
    
    def __init__(
        self,
        briefing: Optional[Dict[str, Any]] = None,
    ):
        self._briefing = briefing or {
            "briefing_type": "daily_morning",
            "generated_at": datetime.now().isoformat(),
            "sections": {
                "critical_items": [],
                "overnight_anomalies": [],
                "optimization_wins": [],
                "today_context": {},
                "recommendations": [],
            }
        }
        self._call_count = 0
    
    async def generate_briefing(
        self,
        briefing_type: str = "daily_morning",
        focus_area: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._call_count += 1
        briefing = self._briefing.copy()
        briefing["briefing_type"] = briefing_type
        briefing["focus_area"] = focus_area
        return briefing
    
    def set_briefing(self, briefing: Dict[str, Any]) -> None:
        self._briefing = briefing


# ============================================================================
# MOCK FEEDBACK LOOP
# ============================================================================

class MockFeedbackLoop:
    """Mock feedback loop for testing."""
    
    def __init__(self):
        self._feedback: List[Dict[str, Any]] = []
        self._call_count = 0
    
    async def submit_feedback(
        self,
        feedback_type: str,
        target: str,
        content: str,
        rating: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._call_count += 1
        feedback = {
            "feedback_type": feedback_type,
            "target": target,
            "content": content,
            "rating": rating,
            "timestamp": datetime.now().isoformat(),
        }
        self._feedback.append(feedback)
        return {
            "status": "recorded",
            "feedback_id": f"FB-{len(self._feedback)}",
        }
    
    def get_feedback(self) -> List[Dict[str, Any]]:
        return self._feedback


# ============================================================================
# MOCK TRUST CALIBRATOR
# ============================================================================

class MockTrustCalibrator:
    """Mock trust calibrator for testing."""
    
    def __init__(
        self,
        trust_score: float = 0.85,
        adoption_rate: float = 0.92,
    ):
        self._trust_score = trust_score
        self._adoption_rate = adoption_rate
        self._call_count = 0
    
    async def calculate_trust_metrics(self, window_days: int = 30) -> Dict[str, Any]:
        self._call_count += 1
        return {
            "trust_score": self._trust_score,
            "adoption_rate": self._adoption_rate,
            "window_days": window_days,
            "total_recommendations": 150,
            "followed_recommendations": int(150 * self._adoption_rate),
        }
    
    def set_trust_score(self, trust_score: float) -> None:
        self._trust_score = trust_score
    
    def set_adoption_rate(self, adoption_rate: float) -> None:
        self._adoption_rate = adoption_rate


# ============================================================================
# MOCK TRACKER
# ============================================================================

class MockTracker:
    """Mock tracker for feedback recording."""
    
    def __init__(self):
        self._records: List[Dict[str, Any]] = []
    
    def record_feedback(self, target: str, feedback_type: str, content: str) -> None:
        self._records.append({
            "target": target,
            "feedback_type": feedback_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
    
    def get_records(self) -> List[Dict[str, Any]]:
        return self._records


# ============================================================================
# MOCK PREDICTIVE ENGINE (ML)
# ============================================================================

class MockPredictiveEngine:
    """
    Mock predictive engine with ML forecasting.
    
    Usage:
        engine = MockPredictiveEngine()
        engine.set_forecast([{"hour": 0, "predicted_kw": 400}])
        engine.add_fault({"equipment_id": "CH-01", "fault_type": "sensor_drift"})
        
        forecast = await engine.forecast_energy(hours=24)
        faults = await engine.detect_faults(equipment_id="CH-01")
    """
    
    def __init__(self):
        self._forecasts: List[Dict[str, Any]] = []
        self._faults: List[Dict[str, Any]] = []
        self._rul_predictions: Dict[str, Dict[str, Any]] = {}
        self._call_counts: Dict[str, int] = defaultdict(int)
    
    # --- Forecasting ---
    
    def set_forecast(self, forecast: List[Dict[str, Any]]) -> None:
        """Set mock forecast data."""
        self._forecasts = forecast
    
    async def forecast_energy(
        self,
        hours: int = 24,
        building_id: Optional[str] = None,
        include_confidence: bool = True,
    ) -> Dict[str, Any]:
        """Return mock energy forecast."""
        self._call_counts["forecast_energy"] += 1
        
        if self._forecasts:
            return {
                "building_id": building_id or "default",
                "forecast_hours": hours,
                "forecast": self._forecasts[:hours],
                "model": "mock_prophet_lightgbm",
            }
        
        # Generate default forecast
        import random
        forecast = []
        base_load = 400
        
        for hour in range(hours):
            hour_of_day = hour % 24
            load_factor = 1.3 if 6 <= hour_of_day < 18 else 0.7
            predicted = base_load * load_factor * (1 + random.uniform(-0.05, 0.05))
            
            forecast.append({
                "hour": hour,
                "predicted_kw": round(predicted, 1),
                "confidence_low": round(predicted * 0.9, 1) if include_confidence else None,
                "confidence_high": round(predicted * 1.1, 1) if include_confidence else None,
            })
        
        return {
            "building_id": building_id or "default",
            "forecast_hours": hours,
            "forecast": forecast,
            "model": "mock_default",
        }
    
    # --- Fault Detection ---
    
    def add_fault(self, fault: Dict[str, Any]) -> None:
        """Add mock fault."""
        self._faults.append(fault)
    
    def clear_faults(self) -> None:
        """Clear all faults."""
        self._faults.clear()
    
    async def detect_faults(
        self,
        equipment_id: str,
        fault_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return mock fault detection results."""
        self._call_counts["detect_faults"] += 1
        
        faults = [
            f for f in self._faults
            if f.get("equipment_id") == equipment_id
        ]
        
        if fault_type:
            faults = [f for f in faults if f.get("fault_type") == fault_type]
        
        return {
            "equipment_id": equipment_id,
            "faults_detected": faults,
            "status": "fault" if faults else "normal",
            "confidence": 0.92 if faults else 0.85,
        }
    
    # --- RUL ---
    
    def set_rul_prediction(self, equipment_id: str, prediction: Dict[str, Any]) -> None:
        """Set RUL prediction for equipment."""
        self._rul_predictions[equipment_id] = prediction
    
    async def predict_rul(
        self,
        equipment_id: str,
        forecast_days: int = 90,
    ) -> Dict[str, Any]:
        """Return mock RUL prediction."""
        self._call_counts["predict_rul"] += 1
        
        if equipment_id in self._rul_predictions:
            return self._rul_predictions[equipment_id]
        
        return {
            "equipment_id": equipment_id,
            "health_score": 85,
            "days_until_predicted_failure": 180,
            "failure_probability": {
                "30_days": 0.05,
                "60_days": 0.12,
                "90_days": 0.25,
            },
            "degradation_indicators": ["Normal wear"],
            "recommendation": "Continue monitoring",
        }
    
    # --- Maintenance ---
    
    async def predict_maintenance(self, equipment_id: str = "all") -> Dict[str, Any]:
        """Return mock maintenance prediction."""
        self._call_counts["predict_maintenance"] += 1
        
        if equipment_id == "all":
            return [
                {
                    "equipment_id": "CH-01",
                    "next_maintenance": "2026-06-15",
                    "health_score": 82,
                    "priority": "medium",
                }
            ]
        
        return {
            "equipment_id": equipment_id,
            "next_maintenance": "2026-06-15",
            "health_score": 82,
            "priority": "medium",
        }
    
    def get_call_counts(self) -> Dict[str, int]:
        """Return call counts for assertions."""
        return dict(self._call_counts)


# ============================================================================
# MOCK WORLD MODEL (Bayesian / Simulation)
# ============================================================================

class MockWorldModel:
    """
    Mock world model for Bayesian root cause and simulation.
    
    Usage:
        model = MockWorldModel()
        model.add_root_cause({"cause": "CH-01 trip", "probability": 0.85})
        model.set_simulation_result({"energy_impact_pct": -5.2})
        
        root_cause = await model.analyze_root_cause(alarm_ids=["ALM-1"])
        sim = await model.simulate_with_uncertainty(...)
    """
    
    def __init__(self):
        self._root_causes: List[Dict[str, Any]] = []
        self._simulation_result: Dict[str, Any] = {}
        self._benchmark: Dict[str, Any] = {}
        self._call_counts: Dict[str, int] = defaultdict(int)
    
    # --- Root Cause ---
    
    def add_root_cause(self, cause: Dict[str, Any]) -> None:
        """Add mock root cause."""
        self._root_causes.append(cause)
    
    async def analyze_root_cause(
        self,
        alarm_ids: List[str],
        depth: int = 3,
    ) -> Dict[str, Any]:
        """Return mock root cause analysis."""
        self._call_counts["analyze_root_cause"] += 1
        
        return {
            "alarm_ids": alarm_ids,
            "root_causes": self._root_causes if self._root_causes else [
                {"cause": "Unknown", "probability": 0.5, "evidence": []}
            ],
            "cascade_prediction": None,
            "analysis_depth": depth,
        }
    
    # --- Simulation ---
    
    def set_simulation_result(self, result: Dict[str, Any]) -> None:
        """Set mock simulation result."""
        self._simulation_result = result
    
    async def simulate_with_uncertainty(
        self,
        change_type: str,
        current_value: float,
        proposed_value: float,
        equipment_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        samples: int = 1000,
    ) -> Dict[str, Any]:
        """Return mock simulation with uncertainty."""
        self._call_counts["simulate_with_uncertainty"] += 1
        
        if self._simulation_result:
            return self._simulation_result
        
        delta = proposed_value - current_value
        energy_impact = -delta * 2.5
        
        return {
            "change_type": change_type,
            "current_value": current_value,
            "proposed_value": proposed_value,
            "energy_impact_pct": round(energy_impact, 1),
            "energy_impact_kwh": round(abs(delta) * 10, 1),
            "comfort_impact": "minimal" if abs(delta) <= 1 else "moderate",
            "risk_assessment": {
                "worst_case": round(energy_impact * 1.5, 1),
                "best_case": round(energy_impact * 0.5, 1),
                "probability_negative": 0.1 if delta > 0 else 0.3,
            },
            "monte_carlo_samples": samples,
        }
    
    # --- Benchmark ---
    
    def set_benchmark(self, benchmark: Dict[str, Any]) -> None:
        """Set mock benchmark data."""
        self._benchmark = benchmark
    
    async def benchmark_building(
        self,
        building_id: Optional[str] = None,
        scope: str = "local_fleet",
    ) -> Dict[str, Any]:
        """Return mock building benchmark."""
        self._call_counts["benchmark_building"] += 1
        
        if self._benchmark:
            return self._benchmark
        
        return {
            "building_id": building_id or "default",
            "archetype": "Large Office Cooling-Dominated",
            "percentile_rankings": {
                "energy_eui": 65,
                "gsas_score": 72,
                "maintenance_cost": 58,
            },
            "comparison_scope": scope,
            "improvement_opportunities": [
                {"area": "Cooling efficiency", "potential_savings_qar": 15000},
            ],
        }
    
    def get_call_counts(self) -> Dict[str, int]:
        """Return call counts for assertions."""
        return dict(self._call_counts)


# ============================================================================
# MOCK KNOWLEDGE BASE (Semantic Search)
# ============================================================================

class MockKnowledgeBase:
    """
    Mock knowledge base for semantic skill search.
    
    Usage:
        kb = MockKnowledgeBase()
        kb.add_skill({"skill_id": "SK-01", "title": "Chiller optimization", "similarity": 0.92})
        
        results = await kb.find_similar_skills(query="chiller not cooling")
    """
    
    def __init__(self):
        self._skills: List[Dict[str, Any]] = []
        self._call_counts: Dict[str, int] = defaultdict(int)
    
    def add_skill(self, skill: Dict[str, Any]) -> None:
        """Add mock skill."""
        self._skills.append(skill)
    
    def clear_skills(self) -> None:
        """Clear all skills."""
        self._skills.clear()
    
    async def find_similar_skills(
        self,
        query: str,
        top_k: int = 5,
        equipment_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return mock similar skills."""
        self._call_counts["find_similar_skills"] += 1
        
        skills = self._skills[:top_k]
        
        if equipment_type:
            skills = [s for s in skills if s.get("equipment_type") == equipment_type][:top_k]
        
        return {
            "query": query,
            "results": skills,
            "model": "mock_embeddings",
        }
    
    def get_call_counts(self) -> Dict[str, int]:
        """Return call counts for assertions."""
        return dict(self._call_counts)


# ============================================================================
# MOCK ENGINES
# ============================================================================

class MockAlarmEngine:
    """Mock alarm engine for testing."""
    
    def __init__(self, alarms=None):
        self._alarms = alarms or []
        self._clusters = []
    
    def add_alarm(self, alarm):
        self._alarms.append(alarm)
    
    def get_active_alarms(self, priority_filter=None):
        if priority_filter:
            return [a for a in self._alarms if a.get("severity") == priority_filter]
        return self._alarms
    
    def acknowledge_alarm(self, alarm_id, user="test", note=""):
        for alarm in self._alarms:
            if alarm.get("alarm_id") == alarm_id:
                alarm["status"] = "acknowledged"
                return True
        return False
    
    def cluster_alarms(self):
        return self._clusters
    
    def get_stats(self):
        return {
            "active_alarms": len(self._alarms),
            "clusters": len(self._clusters),
        }


class MockBriefingScheduler:
    """Mock briefing scheduler for testing."""
    
    def __init__(self):
        self._briefings = []
    
    async def generate_briefing(self, briefing_type="daily_morning", focus_area=None):
        return {
            "briefing_type": briefing_type,
            "generated_at": datetime.now().isoformat(),
            "sections": {
                "critical_items": [],
                "overnight_anomalies": [],
                "optimization_wins": [],
                "recommendations": [],
            },
        }
    
    def get_stats(self):
        return {"briefings_generated": len(self._briefings)}


class MockGoalGenerator:
    """Mock goal generator for testing."""
    
    def __init__(self):
        self._goals = []
    
    def add_goal(self, goal):
        self._goals.append(goal)
    
    def get_active_goals(self, category=None):
        if category:
            return [g for g in self._goals if g.get("category") == category]
        return self._goals


class MockFeedbackLoop:
    """Mock feedback loop for testing."""
    
    def __init__(self):
        self._feedback = []
    
    async def submit_feedback(self, feedback_type, target, content, rating=None):
        self._feedback.append({
            "type": feedback_type,
            "target": target,
            "content": content,
            "rating": rating,
        })
        return {"status": "recorded"}


class MockTrustCalibrator:
    """Mock trust calibrator for testing."""
    
    async def calculate_trust_metrics(self, window_days=30):
        return {
            "trust_score": 0.85,
            "adoption_rate": 0.72,
            "accuracy": 0.88,
        }


class MockPredictiveEngine:
    """Mock predictive engine for testing."""
    
    async def predict_maintenance(self, equipment_id):
        return {
            "equipment_id": equipment_id,
            "failure_probability": 0.15,
            "rul_days": 45,
            "health_score": 85,
        }
    
    async def predict_rul(self, equipment_id, forecast_days):
        return {
            "equipment_id": equipment_id,
            "days_until_predicted_failure": 60,
            "health_score": 82,
            "failure_probability": {
                "30_days": 0.08,
                "60_days": 0.18,
                "90_days": 0.32,
            },
        }
    
    async def detect_faults(self, equipment_id, fault_type=None):
        return {
            "equipment_id": equipment_id,
            "faults_detected": [],
            "status": "normal",
            "confidence": 0.85,
        }
    
    async def forecast_energy(self, hours=24, building_id=None, include_confidence=True):
        import random
        forecast = []
        for hour in range(hours):
            forecast.append({
                "hour": hour,
                "predicted_kw": 400 + random.uniform(-20, 20),
            })
        return {
            "forecast": forecast,
            "peak_demand": 450,
        }


class MockGSASReporter:
    """Mock GSAS reporter for testing."""
    
    def __init__(self, building_id="TEST-001", target_rating=4):
        self.building_id = building_id
        self.target_rating = target_rating
        self._score = 2.5
    
    def get_status(self):
        return {
            "overall_score": self._score,
            "certification_level": "3-Star",
            "categories": {
                "energy": 75,
                "water": 70,
                "indoor_environment": 80,
            },
        }
    
    def target_score(self):
        return self.target_rating * 0.75
    
    def get_improvement_priorities(self):
        return [
            {"action": "Optimize Chiller Sequencing", "impact": 1.5, "category": "Energy"},
            {"action": "Install Low-Flow Fixtures", "impact": 0.8, "category": "Water"},
        ]
    
    def optimize_recommendations_for_targets(self, recommendations, limit=10):
        # Return top recommendations sorted by GSAS impact
        sorted_recs = sorted(recommendations, key=lambda r: r.get("gsas_impact", 0), reverse=True)
        return sorted_recs[:limit]


class MockWorldModel:
    """Mock world model for testing."""
    
    async def analyze_root_cause(self, alarm_ids, depth=3):
        return {
            "alarm_ids": alarm_ids,
            "root_causes": [{"cause": "Unknown", "probability": 0.5}],
        }
    
    async def simulate_with_uncertainty(self, **kwargs):
        return {
            "energy_impact_pct": -2.5,
            "risk_assessment": {"probability_negative": 0.1},
        }
    
    def benchmark_building(self, building_id, scope="local_fleet"):
        return {
            "archetype": "Large Office Cooling-Dominated",
            "percentile_rankings": {"energy_eui": 65},
        }


class MockKnowledgeBase:
    """Mock knowledge base for testing."""
    
    async def query_specs(self, query, equipment_id=None, limit=5):
        return [
            {"content": "Sample manual content", "metadata": {"source": "manual.pdf"}},
        ]
    
    async def find_similar_skills(self, query, top_k=5, equipment_type=None):
        return {"results": [], "query": query}


class MockTracker:
    """Mock feedback tracker for testing."""
    
    def __init__(self):
        self._feedback = []
    
    def record_feedback(self, target, feedback_type, content):
        self._feedback.append({"target": target, "type": feedback_type, "content": content})


class MockAdvisor:
    """Mock advisor for testing."""
    
    async def get_recommendations(self, context, equipment_id=None, alarm_id=None, top_k=3):
        return {
            "context": context,
            "recommendations": [
                {"id": "rec-001", "title": "Monitor", "confidence": 0.7},
            ],
        }


class MockOnlineLearner:
    """Mock online learner for testing."""
    
    def __init__(self):
        self._observations = []
    
    def log_observation(self, prediction, actual):
        self._observations.append({"prediction": prediction, "actual": actual})
    
    def get_performance_summary(self):
        return {
            "current_rmse": 0.15,
            "drift_ratio": 1.0,
            "sample_count": len(self._observations),
        }


class MockPredictiveMaintenanceEngine:
    """Mock predictive maintenance engine."""
    
    async def predict_maintenance(self, equipment_id):
        return {
            "equipment_id": equipment_id,
            "failure_probability": 0.12,
            "rul_days": 90,
            "health_score": 88,
            "recommendation": "Continue monitoring",
        }
    
    async def predict_rul(self, equipment_id, forecast_days=90):
        return {
            "equipment_id": equipment_id,
            "days_until_predicted_failure": 180,
            "health_score": 85,
        }
    
    def detect_faults(self, equipment_id, fault_type=None):
        return {
            "equipment_id": equipment_id,
            "faults_detected": [],
        }


# ============================================================================
# UPDATED MOCK BMS STATE ENGINE (with all required methods)
# ============================================================================

class MockBMSStateEngineV2:
    """
    Enhanced mock BMS state engine matching real interface.
    Returns objects with .to_dict() methods instead of raw dicts.
    """
    
    def __init__(self):
        self._equipment: Dict[str, Any] = {}
        self._points: Dict[str, Any] = {}
        self._point_history: Dict[str, List] = defaultdict(list)
        self._alarms: List[Any] = []
        self._callbacks: List[Callable] = []
    
    def add_equipment(self, equipment: Dict[str, Any]) -> None:
        eq_id = equipment.get("equipment_id")
        if eq_id:
            # Wrap in object with to_dict
            self._equipment[eq_id] = MockEquipment(equipment)
    
    def get_equipment(self, equipment_id: str):
        return self._equipment.get(equipment_id)
    
    def get_all_equipment(self) -> List:
        return list(self._equipment.values())
    
    def update_point(self, point_id: str, value: float, unit: str = "", equipment_id: str = "", timestamp=None):
        ts = timestamp or datetime.now()
        point = MockDataPoint({
            "point_id": point_id,
            "value": value,
            "unit": unit,
            "equipment_id": equipment_id,
            "timestamp": ts,
        })
        self._points[point_id] = point
        self._point_history[point_id].append((ts, value))
    
    def get_point(self, point_id: str):
        return self._points.get(point_id)
    
    def get_points_by_equipment(self, equipment_id: str) -> List:
        return [p for p in self._points.values() if p.equipment_id == equipment_id]
    
    def get_point_history(self, point_id: str, hours: int = 24):
        cutoff = datetime.now() - timedelta(hours=hours)
        history = self._point_history.get(point_id, [])
        return [(t, v) for t, v in history if t >= cutoff]
    
    def add_alarm(self, alarm: Dict[str, Any]) -> None:
        alarm.setdefault("alarm_id", f"ALM-{len(self._alarms) + 1}")
        alarm.setdefault("timestamp", datetime.now().isoformat())
        self._alarms.append(MockAlarm(alarm))
    
    def get_active_alarms(self) -> List:
        return [a for a in self._alarms if a.status != "acknowledged"]
    
    def acknowledge_alarm(self, alarm_id: str) -> bool:
        for alarm in self._alarms:
            if alarm.alarm_id == alarm_id:
                alarm.status = "acknowledged"
                return True
        return False
    
    async def get_snapshot(self):
        """Return current state snapshot."""
        return {
            "equipment_count": len(self._equipment),
            "point_count": len(self._points),
            "active_alarms": len(self.get_active_alarms()),
        }
    
    def on_point_update(self, callback: Callable) -> None:
        self._callbacks.append(callback)
    
    def clear(self) -> None:
        self._equipment.clear()
        self._points.clear()
        self._point_history.clear()
        self._alarms.clear()


class MockEquipment:
    """Mock equipment object with to_dict method."""
    
    def __init__(self, data: Dict[str, Any]):
        self.equipment_id = data.get("equipment_id")
        self.name = data.get("name")
        self.equipment_type = MockEnum(data.get("equipment_type", "unknown"))
        self.status = MockEnum(data.get("status", "running"))
        self.location = data.get("location", "")
        self.efficiency = data.get("efficiency", 0.85)
        self._data = data
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


class MockDataPoint:
    """Mock data point object with to_dict method."""
    
    def __init__(self, data: Dict[str, Any]):
        self.point_id = data.get("point_id")
        self.name = data.get("name", data.get("point_id"))
        self.value = data.get("value")
        self.unit = data.get("unit", "")
        self.equipment_id = data.get("equipment_id", "")
        self.timestamp = data.get("timestamp")
        self._data = data
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


class MockAlarm:
    """Mock alarm object with properties."""
    
    def __init__(self, data: Dict[str, Any]):
        self.alarm_id = data.get("alarm_id")
        self.message = data.get("message", "")
        self.severity = data.get("severity", "medium")
        self.status = data.get("status", "active")
        self.timestamp = data.get("timestamp")
        self._data = data
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


class MockEnum:
    """Mock enum with .value property."""
    
    def __init__(self, value: str):
        self.value = value
    
    def __str__(self):
        return self.value
