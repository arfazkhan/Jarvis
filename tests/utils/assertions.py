"""
Test Assertions
===============

Custom assertion helpers for BMS-specific test validation.
"""

from typing import Dict, Any, List


def assert_valid_tool_result(result: Dict[str, Any]):
    """Assert tool result has required fields."""
    assert "status" in result, "Tool result must have 'status'"
    assert result["status"] in ["success", "error"], "Status must be 'success' or 'error'"
    if result["status"] == "success":
        assert "data" in result or "result" in result, "Successful result must have 'data' or 'result'"
    else:
        assert "error" in result, "Error result must have 'error'"


def assert_valid_recommendation(rec: Dict[str, Any]):
    """Assert recommendation has required fields."""
    assert "recommendation_id" in rec or "id" in rec
    assert "equipment_id" in rec or "title" in rec
    if "confidence" in rec:
        assert 0.0 <= rec["confidence"] <= 1.0
    if "gsas_aligned" in rec:
        assert isinstance(rec["gsas_aligned"], bool)


def assert_valid_alarm(alarm: Dict[str, Any]):
    """Assert alarm has required fields."""
    assert "alarm_id" in alarm
    assert "message" in alarm or "description" in alarm
    if "severity" in alarm:
        assert alarm["severity"] in ["critical", "high", "medium", "low", "info"]


def assert_valid_forecast(forecast: List[Dict[str, Any]]):
    """Assert forecast data is valid."""
    assert isinstance(forecast, list)
    assert len(forecast) > 0
    for item in forecast:
        assert "predicted_kw" in item or "predicted_kwh" in item
        if "confidence_low" in item:
            assert item["confidence_low"] <= item.get("predicted_kw", item.get("predicted_kwh", 0))
        if "confidence_high" in item:
            assert item.get("predicted_kw", item.get("predicted_kwh", 0)) <= item["confidence_high"]


def assert_valid_gsas_status(status: Dict[str, Any]):
    """Assert GSAS status is valid."""
    assert "overall_score" in status or "score" in status
    if "certification_level" in status:
        assert "Star" in status["certification_level"] or "star" in status["certification_level"]
    if "categories" in status:
        assert isinstance(status["categories"], dict)
