from typing import List, Callable, Dict, Any, Optional
import pytest
from datetime import datetime
from agent_commercial.gsas_reporter import GSASReporter, GSASStarRating

@pytest.fixture
def gsas_reporter():
    reporter = GSASReporter(
        building_id="TEST-BLDG-01",
        building_name="Test Building",
        target_rating=GSASStarRating.THREE_STAR
    )
    reporter.initialize_criteria()
    
    # Set all criteria to a baseline healthy level (e.g., 2.0 points)
    # This prevents default 0.0 scores from triggering alerts in unrelated tests
    for c_id in reporter.criteria:
        reporter.set_criterion_score(c_id, 2.0)
    
    return reporter

def test_energy_disqualification_fires_callback(gsas_reporter):
    """Test that energy score at 0.0 triggers a critical disqualification alert."""
    alerts = []
    def callback(alert):
        alerts.append(alert)
    
    gsas_reporter.on_disqualification(callback)
    
    # Manually set energy criteria to 0.0 to test the guard
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 0.0)
    
    # Trigger check
    alert = gsas_reporter.check_disqualification()
    
    assert alert is not None
    assert alert["type"] == "gsas_disqualification"
    assert alert["severity"] == "critical"
    assert alert["category"] == "E"
    assert len(alerts) == 1
    assert alerts[0]["type"] == "gsas_disqualification"
    assert gsas_reporter._disqualification_active is True

def test_water_disqualification_fires_callback(gsas_reporter):
    """Test that water score at 0.0 triggers a critical disqualification alert."""
    alerts = []
    def callback(alert):
        alerts.append(alert)
    
    gsas_reporter.on_disqualification(callback)
    
    # Ensure Energy is healthy
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 2.0)
            
    # Manually set water criteria to 0.0
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("W."):
            gsas_reporter.set_criterion_score(c_id, 0.0)
    
    alert = gsas_reporter.check_disqualification()
    
    assert alert is not None
    assert alert["category"] == "W"
    assert alert["severity"] == "critical"
    assert gsas_reporter._disqualification_active is True

def test_warning_before_disqualification(gsas_reporter):
    """Test that scores near the threshold trigger a high-severity warning."""
    alerts = []
    def callback(alert):
        alerts.append(alert)
    
    gsas_reporter.on_disqualification(callback)
    
    # Set energy score just above 0.0 but below 0.3
    # Total points in Energy: E.1(3)+E.2(3)+E.3(2)+E.4(3)+E.5(2)+E.6(2) = 15
    # If we set E.1 to 1.0 and others to 0, total = 1.0
    # Normalized = (1.0/15.0)*3.0 = 0.2
    
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 0.0)
    
    gsas_reporter.set_criterion_score("E.1", 1.0)
        
    alert = gsas_reporter.check_disqualification()
    
    assert alert is not None
    assert alert["type"] == "gsas_disqualification_warning"
    assert alert["severity"] == "high"
    assert gsas_reporter._disqualification_active is False # Warning doesn't set the flag

def test_healthy_scores_clear_disqualification(gsas_reporter):
    """Test that state restores when scores improve."""
    # First, disqualify Energy
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 0.0)
            
    gsas_reporter.check_disqualification()
    assert gsas_reporter._disqualification_active is True
    
    # Now improve Energy (Water is already 2.0 from fixture)
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 2.0)
    
    alert = gsas_reporter.check_disqualification()
    
    assert alert is None
    assert gsas_reporter._disqualification_active is False

def test_get_status_includes_disqualification_risk(gsas_reporter):
    """Verify that get_status reports the disqualification state correctly."""
    # Healthy state
    status = gsas_reporter.get_status()
    assert status["disqualification_risk"] is False
    
    # Disqualified state
    for c_id in gsas_reporter.criteria:
        if c_id.startswith("E."):
            gsas_reporter.set_criterion_score(c_id, 0.0)
            
    gsas_reporter.check_disqualification()
    
    status = gsas_reporter.get_status()
    assert status["disqualification_risk"] is True
    assert status["on_track"] is False
