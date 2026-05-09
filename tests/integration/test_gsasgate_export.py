import pytest
import json
import os
from datetime import datetime
from agent_commercial.gsas_reporter import GSASReporter, CriterionStatus
from agent_commercial.gsasgate_exporter import GSASgateExporter

@pytest.fixture
def populated_reporter():
    reporter = GSASReporter("BUILDING-TEST", "Integration Test Building")
    reporter.initialize_criteria()
    
    # Manually set some scores to simulate a real assessment
    reporter.update_from_bms(
        energy_data={"consumption_vs_baseline": 25, "submetering_coverage": 95},
        water_data={"consumption_vs_baseline": 15, "submetering_coverage": 100},
        iaq_data={"comfort_compliance": 90}
    )
    return reporter

def test_json_export_structure(populated_reporter):
    """Test that JSON export contains all required GSASgate fields."""
    exporter = GSASgateExporter(populated_reporter)
    json_str = exporter.export_json()
    data = json.loads(json_str)
    
    assert data["metadata"]["portal"] == "GSASgate-OPS"
    assert data["metadata"]["building"]["id"] == "BUILDING-TEST"
    assert data["assessment"]["overall_score"] > 0
    
    # Check for Energy criteria
    energy_crit = next(c for c in data["criteria_details"] if c["id"] == "E.1")
    assert energy_crit["points"] == 1.5 # 25% reduction -> 1.5 pts
    assert energy_crit["status"] == "achieved"

def test_csv_export_format(populated_reporter):
    """Test that CSV export contains correct headers and data."""
    exporter = GSASgateExporter(populated_reporter)
    csv_str = exporter.export_csv()
    lines = csv_str.strip().split("\n")
    
    header = lines[0]
    assert "Criterion ID" in header
    assert "Points Achieved" in header
    
    # Check a specific row
    water_row = next(l for l in lines if l.startswith("W.3"))
    # W.3: 100% coverage -> 2.0 pts
    assert "2.0" in water_row
    assert "exceeds" in water_row

def test_file_persistence(populated_reporter):
    """Test that exporter saves files to the correct directory."""
    exporter = GSASgateExporter(populated_reporter)
    filename = "test_export.json"
    filepath = exporter.save_to_file(filename, format="json")
    
    assert os.path.exists(filepath)
    assert "exports/gsasgate" in filepath
    
    with open(filepath, "r") as f:
        data = json.load(f)
        assert data["metadata"]["building"]["name"] == "Integration Test Building"
    
    # Cleanup
    os.remove(filepath)
