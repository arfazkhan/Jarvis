"""
verify_tool_schema_compliance.py
=================================
Smoke-test the infrastructure fixes:
  1. detect_equipment_faults  → must always return 'faults' + 'health_score'
  2. get_zone_occupancy       → must always return flat schema keys
  3. get_gsas_success_rates   → must always return 'overall_approval_rate' etc.

Also tests BaseToolHandler._validate_output backfill logic.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SCHEMA_REQUIRED = {
    "detect_equipment_faults": ["faults", "health_score"],
    "get_zone_occupancy": [
        "zone_id", "is_occupied", "occupancy_probability",
        "occupancy_pattern", "signals_used", "confidence",
    ],
    "get_gsas_success_rates": [
        "overall_approval_rate", "by_action_type", "total_recorded",
        "most_rejected_type",
    ],
}

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check_keys(result: dict, required_keys: list, label: str) -> bool:
    missing = [k for k in required_keys if k not in result]
    if missing:
        print(f"  {FAIL} [{label}] missing keys: {missing}")
        return False
    print(f"  {PASS} [{label}] all schema keys present: {required_keys}")
    return True


async def test_detect_equipment_faults():
    """Test all code paths of detect_equipment_faults."""
    print("\n=== detect_equipment_faults ===")
    from agent_commercial.tools.handlers.ml import MLHandlerMixin

    # Build minimal mock handler
    class MockHandler(MLHandlerMixin):
        predictive_engine = None
        memory_orchestrator = None
        knowledge_base = None

    handler = MockHandler()
    req = SCHEMA_REQUIRED["detect_equipment_faults"]

    # Path 1: no equipment_id (error path)
    r = await handler._handle_detect_equipment_faults({})
    check_keys(r, req, "no equipment_id")

    # Path 2: predictive_engine not configured (fallback)
    r = await handler._handle_detect_equipment_faults({"equipment_id": "AHU-01"})
    check_keys(r, req, "fallback (no engine)")

    # Path 3: engine returns legacy key name
    class LegacyEngine:
        async def detect_faults(self, equipment_id, fault_type):
            return {"faults_detected": [{"type": "AIRFLOW_RESTRICTION"}], "status": "fault"}

    handler.predictive_engine = LegacyEngine()
    r = await handler._handle_detect_equipment_faults({"equipment_id": "AHU-01"})
    check_keys(r, req, "engine returns legacy 'faults_detected'")
    assert r["faults"] == [{"type": "AIRFLOW_RESTRICTION"}], f"Alias failed: {r}"
    print(f"  {PASS} [alias] 'faults_detected' correctly aliased to 'faults'")

    # Path 4: engine returns correct keys
    class GoodEngine:
        async def detect_faults(self, equipment_id, fault_type):
            return {"faults": [], "health_score": 92.5, "confidence": 0.87}

    handler.predictive_engine = GoodEngine()
    r = await handler._handle_detect_equipment_faults({"equipment_id": "AHU-01"})
    check_keys(r, req, "engine returns correct keys")


async def test_get_zone_occupancy():
    """Test all code paths of get_zone_occupancy."""
    print("\n=== get_zone_occupancy ===")
    from agent_commercial.tools.handlers.gsas import GSASHandlerMixin

    class MockHandler(GSASHandlerMixin):
        bms_state = None

    handler = MockHandler()
    req = SCHEMA_REQUIRED["get_zone_occupancy"]

    # Path 1: no zone_id
    r = await handler._handle_get_zone_occupancy({})
    check_keys(r, req, "no zone_id")

    # Path 2: OccupancyContextProvider unavailable — patched to None
    import agent_commercial.tools.handlers.gsas as gsas_mod
    original = gsas_mod.OccupancyContextProvider
    gsas_mod.OccupancyContextProvider = None
    r = await handler._handle_get_zone_occupancy({"zone_id": "floor_7_zone_a"})
    check_keys(r, req, "provider unavailable")
    assert "warning" in r, "Should include a 'warning' key"
    gsas_mod.OccupancyContextProvider = original

    # Path 3: provider returns flat dict
    class FlatProvider:
        def __init__(self, bms_state): pass
        def get_zone_occupancy(self, zone_id):
            return {
                "is_occupied": True, "occupancy_probability": 0.87,
                "occupancy_pattern": {"peak": "09:00-17:00"},
                "signals_used": ["CO2", "motion"],
                "confidence": 0.91,
            }

    gsas_mod.OccupancyContextProvider = FlatProvider
    r = await handler._handle_get_zone_occupancy({"zone_id": "floor_7_zone_a"})
    check_keys(r, req, "provider returns flat dict")

    # Path 4: provider returns legacy nested wrapper
    class NestedProvider:
        def __init__(self, bms_state): pass
        def get_zone_occupancy(self, zone_id):
            return {"occupancy_context": {
                "is_occupied": False, "occupancy_probability": 0.1,
                "occupancy_pattern": {}, "signals_used": [], "confidence": 0.5,
            }}

    gsas_mod.OccupancyContextProvider = NestedProvider
    r = await handler._handle_get_zone_occupancy({"zone_id": "floor_7_zone_a"})
    check_keys(r, req, "provider returns nested 'occupancy_context' wrapper")

    gsas_mod.OccupancyContextProvider = original


async def test_get_gsas_success_rates():
    """Test all code paths of get_gsas_success_rates."""
    print("\n=== get_gsas_success_rates ===")
    from agent_commercial.tools.handlers.gsas import GSASHandlerMixin

    class MockHandler(GSASHandlerMixin):
        bms_state = None
        gsas_reporter = None

    handler = MockHandler()
    req = SCHEMA_REQUIRED["get_gsas_success_rates"]

    import agent_commercial.tools.handlers.gsas as gsas_mod
    original_tracker = gsas_mod.GSASOutcomeTracker
    original_db = gsas_mod.get_database

    # Path 1: GSASOutcomeTracker unavailable
    gsas_mod.GSASOutcomeTracker = None
    r = await handler._handle_get_gsas_success_rates({})
    check_keys(r, req, "tracker unavailable")

    # Path 2: tracker returns partial dict (missing most_rejected_type)
    class PartialTracker:
        def __init__(self, db): pass
        def get_success_rates(self, action_type):
            return {"overall_approval_rate": 0.73, "by_action_type": {}, "total_recorded": 15}

    gsas_mod.GSASOutcomeTracker = PartialTracker
    gsas_mod.get_database = lambda: None
    r = await handler._handle_get_gsas_success_rates({})
    check_keys(r, req, "tracker returns partial dict")
    assert r["most_rejected_type"] is None, f"Expected None, got {r['most_rejected_type']}"
    print(f"  {PASS} [default] 'most_rejected_type' correctly defaulted to None")

    # Path 3: tracker returns full dict
    class FullTracker:
        def __init__(self, db): pass
        def get_success_rates(self, action_type):
            return {
                "overall_approval_rate": 0.81,
                "by_action_type": {"setpoint_adjustment": 0.9},
                "total_recorded": 42,
                "most_rejected_type": "chiller_sequence",
            }

    gsas_mod.GSASOutcomeTracker = FullTracker
    r = await handler._handle_get_gsas_success_rates({})
    check_keys(r, req, "tracker returns full dict")
    assert r["most_rejected_type"] == "chiller_sequence"
    print(f"  {PASS} [full] 'most_rejected_type' correctly preserved: chiller_sequence")

    gsas_mod.GSASOutcomeTracker = original_tracker
    gsas_mod.get_database = original_db


async def test_validate_output_backfill():
    """Test _validate_output strengthened backfill."""
    print("\n=== BaseToolHandler._validate_output ===")
    from agent_commercial.tools.handlers.base import BMSToolHandler

    handler = BMSToolHandler()
    tool_def = {
        "response_schema": {
            "type": "object",
            "properties": {
                "faults": {"type": "array"},
                "health_score": {"type": "number"},
                "confidence": {"type": "number"},
            }
        }
    }

    # Missing keys get backfilled
    result = {"equipment_id": "AHU-01"}
    out = handler._validate_output("detect_equipment_faults", result, tool_def)
    assert out["faults"] == [], f"faults not backfilled: {out}"
    assert out["health_score"] == 0, f"health_score not backfilled: {out}"
    assert "_schema_violation" in out
    print(f"  {PASS} [backfill] missing keys correctly backfilled")

    # Pure error dict exempt from backfill
    result2 = {"error": "equipment_id is required"}
    out2 = handler._validate_output("detect_equipment_faults", result2, tool_def)
    assert "_schema_violation" not in out2
    print(f"  {PASS} [exempt] pure error dict not polluted with phantom zeros")

    # Non-dict wrapped safely
    out3 = handler._validate_output("detect_equipment_faults", "bad_string", tool_def)
    assert isinstance(out3, dict)
    print(f"  {PASS} [non-dict] non-dict result wrapped safely")


async def main():
    print("=" * 60)
    print("  ARVIS TOOL SCHEMA COMPLIANCE VERIFICATION")
    print("=" * 60)
    await test_detect_equipment_faults()
    await test_get_zone_occupancy()
    await test_get_gsas_success_rates()
    await test_validate_output_backfill()
    print("\n" + "=" * 60)
    print("  ALL CHECKS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
