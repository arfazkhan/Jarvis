"""
Test Utilities
=============

Helper functions, assertions, and utilities for testing.

"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pytest


# ============================================================================
# ASSERTIONS
# ============================================================================

def assert_valid_tool_result(result: Dict[str, Any]) -> None:
    """
    Assert tool result has required fields.
    
    Expected structure:
        {
            "status": "success" | "error",
            "data": {...} | None,
            "error": str | None
        }
    """
    assert "status" in result, "Tool result must have 'status'"
    assert result["status"] in ["success", "error"], "Status must be 'success' or 'error'"
    
    if result["status"] == "success":
        assert "data" in result, "Successful result must have 'data'"
    else:
        assert "error" in result, "Error result must have 'error'"


def assert_valid_recommendation(rec: Dict[str, Any]) -> None:
    """
    Assert recommendation has required fields.
    
    Expected structure:
        {
            "recommendation_id": str,
            "equipment_id": str,
            "action": str,
            "confidence": float (0-1),
            "gsas_aligned": bool,
            "priority": str
        }
    """
    assert "recommendation_id" in rec, "Recommendation must have 'recommendation_id'"
    assert "equipment_id" in rec, "Recommendation must have 'equipment_id'"
    assert "action" in rec, "Recommendation must have 'action'"
    assert "confidence" in rec, "Recommendation must have 'confidence'"
    assert "gsas_aligned" in rec, "Recommendation must have 'gsas_aligned'"
    
    assert 0.0 <= rec["confidence"] <= 1.0, "Confidence must be between 0 and 1"


def assert_valid_prediction(pred: Dict[str, Any]) -> None:
    """
    Assert prediction has required fields.
    
    Expected structure:
        {
            "prediction_id": str,
            "equipment_id": str,
            "predicted_value": float,
            "confidence": float (0-1),
            "horizon_hours": int
        }
    """
    assert "prediction_id" in pred, "Prediction must have 'prediction_id'"
    assert "equipment_id" in pred, "Prediction must have 'equipment_id'"
    assert "predicted_value" in pred, "Prediction must have 'predicted_value'"
    assert "confidence" in pred, "Prediction must have 'confidence'"
    assert "horizon_hours" in pred, "Prediction must have 'horizon_hours'"
    
    assert 0.0 <= pred["confidence"] <= 1.0, "Confidence must be between 0 and 1"


def assert_valid_gsas_score(score: Dict[str, Any]) -> None:
    """
    Assert GSAS score has required fields.
    
    Expected structure:
        {
            "overall_score": float (0-3),
            "star_rating": int (1-6),
            "categories": {...}
        }
    """
    assert "overall_score" in score, "GSAS score must have 'overall_score'"
    assert "star_rating" in score, "GSAS score must have 'star_rating'"
    assert "categories" in score, "GSAS score must have 'categories'"
    
    assert 0.0 <= score["overall_score"] <= 3.0, "Overall score must be between 0 and 3"
    assert 1 <= score["star_rating"] <= 6, "Star rating must be between 1 and 6"


def assert_valid_alarm(alarm: Dict[str, Any]) -> None:
    """
    Assert alarm has required fields.
    
    Expected structure:
        {
            "alarm_id": str,
            "equipment_id": str,
            "message": str,
            "severity": str,
            "status": str
        }
    """
    assert "alarm_id" in alarm, "Alarm must have 'alarm_id'"
    assert "equipment_id" in alarm, "Alarm must have 'equipment_id'"
    assert "message" in alarm, "Alarm must have 'message'"
    assert "severity" in alarm, "Alarm must have 'severity'"
    assert "status" in alarm, "Alarm must have 'status'"
    
    assert alarm["severity"] in ["critical", "warning", "info"], "Invalid severity"
    assert alarm["status"] in ["active", "acknowledged", "cleared"], "Invalid status"


def assert_valid_briefing(briefing: Dict[str, Any]) -> None:
    """
    Assert briefing has required fields.
    
    Expected structure:
        {
            "briefing_id": str,
            "period": str,
            "critical": [...],
            "anomalies": [...],
            "wins": [...]
        }
    """
    assert "briefing_id" in briefing, "Briefing must have 'briefing_id'"
    assert "period" in briefing, "Briefing must have 'period'"
    assert "critical" in briefing, "Briefing must have 'critical'"
    assert "anomalies" in briefing, "Briefing must have 'anomalies'"
    assert "wins" in briefing, "Briefing must have 'wins'"


def assert_valid_verification(verdict: Dict[str, Any]) -> None:
    """
    Assert verification verdict has required fields.
    
    Expected structure:
        {
            "outcome": "validated" | "escalated" | "rejected",
            "confidence": float (0-1),
            "operator_feedback": str | None
        }
    """
    assert "outcome" in verdict, "Verification must have 'outcome'"
    assert "confidence" in verdict, "Verification must have 'confidence'"
    
    assert verdict["outcome"] in ["validated", "escalated", "rejected"], "Invalid outcome"
    assert 0.0 <= verdict["confidence"] <= 1.0, "Confidence must be between 0 and 1"


# ============================================================================
# TIMING UTILITIES
# ============================================================================

class Timer:
    """Context manager for timing code blocks."""
    
    def __init__(self, name: str = "operation"):
        self.name = name
        self.start_time = None
        self.end_time = None
        self.duration_ms = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
    
    def __str__(self) -> str:
        if self.duration_ms is None:
            return f"{self.name}: not finished"
        return f"{self.name}: {self.duration_ms:.2f}ms"


def assert_completes_within(func: Callable, timeout_seconds: float) -> Any:
    """
    Assert that an async function completes within a timeout.
    
    Usage:
        result = assert_completes_within(my_async_func, 5.0)
    """
    async def wrapper():
        return await func()
    
    try:
        return asyncio.run(asyncio.wait_for(wrapper(), timeout=timeout_seconds))
    except asyncio.TimeoutError:
        pytest.fail(f"Function did not complete within {timeout_seconds}s")


async def wait_for_condition(
    condition: Callable[[], bool],
    timeout_seconds: float = 5.0,
    poll_interval_ms: float = 100.0,
) -> None:
    """
    Wait for a condition to become true.
    
    Usage:
        await wait_for_condition(lambda: state.is_connected(), timeout_seconds=10)
    """
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_seconds:
        if condition():
            return
        await asyncio.sleep(poll_interval_ms / 1000.0)
    pytest.fail(f"Condition not met within {timeout_seconds}s")


# ============================================================================
# DATA GENERATION UTILITIES
# ============================================================================

def generate_time_series(
    start: datetime,
    hours: int,
    interval_minutes: int = 60,
    base_value: float = 100.0,
    variance: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Generate a time series of readings.
    
    Usage:
        readings = generate_time_series(
            start=datetime.now() - timedelta(hours=24),
            hours=24,
            base_value=450.0,
        )
    """
    readings = []
    current = start
    for _ in range(hours * 60 // interval_minutes):
        value = base_value + (variance * (2 * (current.hour / 24) - 1))
        value += variance * 0.2 * (2 * random.random() - 1)
        readings.append({
            "timestamp": current.isoformat(),
            "value": round(value, 2),
        })
        current += timedelta(minutes=interval_minutes)
    return readings


def generate_correlated_alarms(
    root_equipment_id: str = "CH-01",
    cascade_count: int = 5,
) -> List[Dict[str, Any]]:
    """
    Generate a cascade of related alarms for testing alarm clustering.
    
    Usage:
        alarms = generate_correlated_alarms("CH-01", cascade_count=10)
    """
    import random
    alarms = []
    
    # Root alarm
    alarms.append({
        "alarm_id": "ALM-ROOT",
        "equipment_id": root_equipment_id,
        "message": f"{root_equipment_id} trip event",
        "severity": "critical",
        "status": "active",
        "timestamp": datetime.now().isoformat(),
    })
    
    # Cascade alarms
    for i in range(cascade_count):
        zone_num = random.randint(1, 20)
        alarms.append({
            "alarm_id": f"ALM-CASCADE-{i}",
            "equipment_id": f"ZONE-{zone_num:02d}",
            "message": f"Zone {zone_num} high temperature",
            "severity": "warning",
            "status": "active",
            "timestamp": (datetime.now() + timedelta(minutes=i)).isoformat(),
        })
    
    return alarms


# ============================================================================
# MOCK CONFIGURATION UTILITIES
# ============================================================================

def configure_mock_llm_for_equipment(mock_llm, equipment_id: str = "CH-01") -> None:
    """Configure MockLLM with equipment-related responses."""
    mock_llm.set_response("status", json.dumps({"equipment_id": equipment_id, "status": "running"}))
    mock_llm.set_response("alarm", json.dumps({"severity": "critical", "equipment_id": equipment_id}))
    mock_llm.set_response("prediction", json.dumps({"predicted_failure": False, "confidence": 0.85}))


def configure_mock_llm_for_gsas(mock_llm, target_rating: int = 4) -> None:
    """Configure MockLLM with GSAS-related responses."""
    mock_llm.set_response("gsas", json.dumps({"score": target_rating * 0.8, "aligned": True}))
    mock_llm.set_response("energy", json.dumps({"savings_potential": 15.0}))


# ============================================================================
# TEST SCENARIO BUILDERS
# ============================================================================

class ScenarioBuilder:
    """Build complex test scenarios."""
    
    def __init__(self):
        self.equipment: List[Dict[str, Any]] = []
        self.points: List[Dict[str, Any]] = []
        self.alarms: List[Dict[str, Any]] = []
        self.predictions: List[Dict[str, Any]] = []
        self.recommendations: List[Dict[str, Any]] = []
    
    def add_chiller(self, equipment_id: str = "CH-01", **kwargs) -> "ScenarioBuilder":
        """Add a chiller to the scenario."""
        from tests.factories import EquipmentFactory, DataPointFactory
        
        self.equipment.append(EquipmentFactory.chiller(equipment_id=equipment_id, **kwargs))
        self.points.extend([
            DataPointFactory.chiller_supply_temp(equipment_id=equipment_id),
            DataPointFactory.chiller_return_temp(equipment_id=equipment_id),
            DataPointFactory.chiller_power(equipment_id=equipment_id),
        ])
        return self
    
    def add_ahu(self, equipment_id: str = "AHU-01", **kwargs) -> "ScenarioBuilder":
        """Add an AHU to the scenario."""
        from tests.factories import EquipmentFactory, DataPointFactory
        
        self.equipment.append(EquipmentFactory.ahu(equipment_id=equipment_id, **kwargs))
        self.points.extend([
            DataPointFactory.ahu_supply_temp(equipment_id=equipment_id),
        ])
        return self
    
    def add_critical_alarm(self, equipment_id: str = "CH-01", **kwargs) -> "ScenarioBuilder":
        """Add a critical alarm to the scenario."""
        from tests.factories import AlarmFactory
        self.alarms.append(AlarmFactory.critical_chiller(equipment_id=equipment_id, **kwargs))
        return self
    
    def add_warning_alarm(self, equipment_id: str = "AHU-01", **kwargs) -> "ScenarioBuilder":
        """Add a warning alarm to the scenario."""
        from tests.factories import AlarmFactory
        self.alarms.append(AlarmFactory.warning_ahu(equipment_id=equipment_id, **kwargs))
        return self
    
    def add_flood_alarms(self, count: int = 50) -> "ScenarioBuilder":
        """Add a flood of alarms for stress testing."""
        from tests.factories import AlarmFactory
        self.alarms.extend(AlarmFactory.flood(count))
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the scenario."""
        return {
            "equipment": self.equipment,
            "points": self.points,
            "alarms": self.alarms,
            "predictions": self.predictions,
            "recommendations": self.recommendations,
        }


# ============================================================================
# SKIP AND MARK UTILITIES
# ============================================================================

def skip_if_no_llm(func: Callable) -> Callable:
    """Skip test if real LLM is not available."""
    import os
    return pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY") and not os.environ.get("GROQ_API_KEY"),
        reason="No LLM API key available"
    )(func)


def skip_if_slow(func: Callable) -> Callable:
    """Skip test if --run-slow is not set."""
    return pytest.mark.skipif(
        not pytest.config.getoption("--run-slow", default=False),
        reason="Slow test, use --run-slow to enable"
    )(func)


def slow_test(func: Callable) -> Callable:
    """Mark test as slow."""
    return pytest.mark.slow(func)


# ============================================================================
# FIXTURE HELPERS
# ============================================================================

def create_isolated_state():
    """Create an isolated MockBMSStateEngine for testing."""
    from tests.mocks import MockBMSStateEngine
    from tests.factories import EquipmentFactory
    
    state = MockBMSStateEngine()
    state.add_equipment(EquipmentFactory.chiller())
    state.add_equipment(EquipmentFactory.ahu())
    return state


def create_isolated_llm():
    """Create an isolated MockLLM for testing."""
    from tests.mocks import MockLLM
    return MockLLM(latency_ms=10.0)  # Fast for tests


def create_test_context(
    equipment_id: str = "CH-01",
    alarm_count: int = 0,
    prediction_confidence: float = 0.85,
) -> Dict[str, Any]:
    """Create a test context dictionary."""
    from tests.factories import AlarmFactory
    
    return {
        "equipment_id": equipment_id,
        "current_time": datetime.now().isoformat(),
        "alarms": [AlarmFactory.random_alarm() for _ in range(alarm_count)],
        "prediction_confidence": prediction_confidence,
    }


# ============================================================================
# IMPORT FOR TESTS
# ============================================================================

# Import random here to avoid issues
import random


def assert_forecast_format(forecast_data):
    """Validate forecast data format."""
    assert isinstance(forecast_data, dict)
    assert "forecast" in forecast_data
    forecast = forecast_data["forecast"]
    assert isinstance(forecast, list)
    for item in forecast:
        assert "hour" in item or "timestamp" in item
        assert "predicted_kw" in item or "predicted_kwh" in item


def assert_energy_anomaly_format(anomaly_data):
    """Validate energy anomaly format."""
    assert isinstance(anomaly_data, dict)
    assert "anomalies" in anomaly_data or "patterns" in anomaly_data


def assert_maintenance_prediction_format(prediction_data):
    """Validate maintenance prediction format."""
    assert isinstance(prediction_data, dict)
    assert "equipment_id" in prediction_data
    if "failure_probability" in prediction_data:
        assert 0 <= prediction_data["failure_probability"] <= 1
    if "health_score" in prediction_data:
        assert 0 <= prediction_data["health_score"] <= 100


def assert_briefing_format(briefing_data):
    """Validate briefing format."""
    assert isinstance(briefing_data, dict)
    assert "briefing_type" in briefing_data
    assert "sections" in briefing_data or "recommendations" in briefing_data


def compare_equipment_states(state1, state2):
    """Compare two equipment states and return differences."""
    differences = {}
    all_keys = set(state1.keys()) | set(state2.keys())
    for key in all_keys:
        if state1.get(key) != state2.get(key):
            differences[key] = {
                "before": state1.get(key),
                "after": state2.get(key),
            }
    return differences
