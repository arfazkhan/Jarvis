"""
GSAS Phase 2 Integration Test
=============================

Verifies the new GSAS-OP compliance features:
1. Waste Tracking (MO.3)
2. Document Ingestion
3. Occupant Surveys (IE.10)
4. Approval Workflow
5. Labels & Scheduling
"""

import asyncio
import json
from datetime import date
from agent_commercial.gsas_reporter import GSASReporter
from agent_commercial.gsasgate_exporter import GSASgateExporter
from agent_commercial.gsas_approval import GSASApprovalWorkflow, PackageStatus
from agent_commercial.waste_tracker import WasteTracker, WasteRecord
from agent_commercial.occupant_surveys import SurveyManager, SurveyResponse
from agent_commercial.document_ingestion import IngestionManager

async def test_gsas_phase2_workflow():
    print("--- STARTING GSAS PHASE 2 INTEGRATION TEST ---")
    
    # 1. Setup Domains
    waste_tracker = WasteTracker()
    survey_manager = SurveyManager()
    
    # 2. Add Waste Data (Manual)
    print("\n[Step 2] Adding manual waste records...")
    waste_tracker.add_record(WasteRecord(
        waste_type="recyclable", quantity_kg=200, disposal_method="recycling", contractor="RecycleCo"
    ))
    waste_tracker.add_record(WasteRecord(
        waste_type="general", quantity_kg=300, disposal_method="landfill", contractor="WasteCo"
    ))
    diversion_rate = waste_tracker.get_diversion_rate()
    print(f"Diversion Rate: {diversion_rate}%")
    
    # 3. Add Survey Data
    print("\n[Step 3] Adding occupant survey responses...")
    survey_manager.add_response(SurveyResponse(thermal_comfort=4, air_quality=4, lighting_quality=5, acoustic_comfort=3))
    survey_manager.add_response(SurveyResponse(thermal_comfort=2, air_quality=3, lighting_quality=4, acoustic_comfort=2))
    ie_data = survey_manager.get_gsas_ie_data()
    print(f"Occupant Satisfaction Rate: {ie_data['satisfaction_rate']}%")
    
    # 4. Document Ingestion (OCR/LLM)
    print("\n[Step 4] Testing document ingestion...")
    ingestor = IngestionManager(waste_tracker=waste_tracker)
    # Simulate waste invoice ingestion
    result = await ingestor.ingest_document("invoices/waste_invoice_may.pdf", "waste_invoice")
    print(f"Ingestion Result: {result['status']} (Confidence: {result['confidence']})")
    print(f"New Diversion Rate: {waste_tracker.get_diversion_rate()}%")
    
    # 5. Reporter Update
    print("\n[Step 5] Updating GSAS Reporter...")
    reporter = GSASReporter("BLDG-TEST", "Test Facility")
    reporter.initialize_criteria()
    
    # Map domain data to reporter
    waste_data = waste_tracker.get_gsas_waste_data()
    ie_data = survey_manager.get_gsas_ie_data()
    
    reporter.update_from_bms(
        energy_data={"consumption_vs_baseline": 15.0}, # 15% reduction
        water_data={"reduction_vs_baseline": 10.0},
        waste_data=waste_data,
        iaq_data={"satisfaction_rate": ie_data["satisfaction_rate"]}
    )
    
    status = reporter.get_status()
    print(f"Overall Score: {status['overall_score']}")
    print(f"Star Rating: {status['star_rating']}")
    print(f"MO.3 (Waste) Score: {reporter.criteria['MO.3'].current_points}")
    print(f"IE.10 (Survey) Score: {reporter.criteria['IE.10'].current_points}")
    
    # 6. Approval Workflow
    print("\n[Step 6] Testing Approval Workflow...")
    approval = GSASApprovalWorkflow()
    exporter = GSASgateExporter(reporter)
    
    package = approval.create_package(reporter, exporter)
    print(f"Created Package: {package.package_id}")
    print(f"Package Status: {package.status.value}")
    print(f"Anomalies Found: {len(package.anomalies)}")
    
    for anomaly in package.anomalies:
        print(f" - [{anomaly.severity}] {anomaly.description}")
        approval.resolve_anomaly(package.package_id, anomaly.id, "Validated with sensor logs")
        
    print("Approving package...")
    approval_res = approval.approve_package(package.package_id, "CSP-ARFAZ")
    print(f"Approval Result: {approval_res['status']}")
    print(f"Final Package Status: {package.status.value}")
    
    print("\n--- GSAS PHASE 2 TEST COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(test_gsas_phase2_workflow())
