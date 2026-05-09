"""
End-to-End Test Suite for ARVIS GSAS-OP Pipeline (Phase 3E)
"""
import pytest
import asyncio
from datetime import datetime
from agent_commercial.gsas_reporter import GSASReporter
from agent_commercial.waste_tracker import WasteTracker, WasteRecord
from agent_commercial.occupant_surveys import SurveyManager, SurveyResponse
from agent_commercial.gsas_approval import GSASApprovalWorkflow
from agent_commercial.gsasgate_exporter import GSASgateExporter

@pytest.fixture
def test_data():
    return {
        "energy": {
            "consumption_vs_baseline": 15.0,  # 15% reduction -> 1.5 points (E.1)
            "submetering_coverage": 85.0,     # >80% -> 1.0 points (E.3)
            "primary_energy_kwh": 400000.0,
            "carbon_emissions_kg": 200000.0,
            "district_cooling_enabled": True  # Exceeds -> 3.0 points (E.5)
        },
        "water": {
            "consumption_vs_baseline": 10.0,
            "leak_detection_active": True
        },
        "maintenance": {
            "fms_compliant": True,
            "cx_completed": True,             # Exceeds -> 3.0 points (MO.1)
            "energy_management_active": True  # Exceeds -> 3.0 points (MO.2)
        }
    }

@pytest.fixture
def components():
    waste_tracker = WasteTracker()
    waste_tracker.add_record(WasteRecord(
        waste_type="mixed",
        quantity_kg=1000,
        disposal_method="recycling"
    ))
    
    survey_manager = SurveyManager()
    survey_manager.add_response(SurveyResponse(
        occupant_type="staff",
        thermal_comfort=4,
        air_quality=5,
        lighting_quality=4,
        acoustic_comfort=3
    ))
    
    approval = GSASApprovalWorkflow()
    return waste_tracker, survey_manager, approval

@pytest.mark.asyncio
async def test_full_gsas_pipeline(test_data, components):
    waste_tracker, survey_manager, approval = components
    
    # 1. Initialize Reporter with Auto-wired managers
    reporter = GSASReporter(
        "TEST-B1", 
        "Test Building",
        waste_tracker=waste_tracker,
        survey_manager=survey_manager
    )
    reporter.initialize_criteria()
    
    # 2. Update from BMS
    reporter.update_from_bms(
        energy_data=test_data["energy"],
        water_data=test_data["water"],
        maintenance_data=test_data["maintenance"]
    )
    
    # 3. Verify Scoring (Phase 3A check)
    status = reporter.get_status()
    # E.2, E.5, MO.1, MO.2 should be scored
    assert status["categories"]["E"]["achieved_points"] > 0
    assert status["categories"]["MO"]["achieved_points"] > 0
    
    # 4. Verify Auto-wiring (Phase 3B check)
    # Waste (MO.3) should have points
    assert reporter.criteria["MO.3"].current_points > 0
    # IE from survey
    assert reporter.criteria["IE.10"].current_points > 0
    
    # 5. Create Package and Exporter
    exporter = GSASgateExporter(reporter)
    package = approval.create_package(reporter, exporter)
    
    # Because there are anomalies by default if some points low
    # We resolve all anomalies to approve
    for anomaly in package.anomalies:
        approval.resolve_anomaly(package.package_id, anomaly.id, "Test resolution")
        
    # 6. Approve Package and auto-export (Phase 3D check)
    result = approval.approve_package(package.package_id, "ADMIN_TEST")
    
    assert result["status"] == "success"
    assert "export_filepath" in result
    
    import os
    assert os.path.exists(result["export_filepath"])
    
    # Cleanup
    if os.path.exists(result["export_filepath"]):
        os.remove(result["export_filepath"])
