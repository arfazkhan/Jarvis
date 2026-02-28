import asyncio
import logging
import time
import json
from datetime import datetime
from agent_commercial.tools.handlers.base import BMSToolHandler
from agent_commercial.skillbook import BuildingSkillbook

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_tool_v3")

async def test_tool_v3():
    print("\n" + "="*60)
    print("ARVIS TOOL V3 VERIFICATION")
    print("="*60)
    
    # 1. Setup Skillbook (Knowledge Base)
    sb = BuildingSkillbook(building_id="test_v3", db_path="test_v3.db")
    
    # 2. Setup Handler
    # We'll pass the skillbook as knowledge_base to verify observability
    handler = BMSToolHandler(knowledge_base=sb)
    
    # --- TEST 1: Structured Error (Unknown Tool) ---
    print("\n[Test 1] Unknown Tool Error Structure...")
    result = await handler.execute("invalid_tool_name", {"arg": "val"})
    
    assert "error" in result, "Result should contain error"
    assert result["error"]["type"] == "UNKNOWN_TOOL", f"Expected UNKNOWN_TOOL, got {result['error']['type']}"
    assert "recovery_hint" in result["error"], "Error should contain recovery_hint"
    print(f"SUCCESS: Received structured error: {result['error']['type']}")
    
    # --- TEST 2: Hard Type Enforcement ---
    print("\n[Test 2] Hard Type Enforcement (String to Int)...")
    # 'limit' is an int_field in _sanitize_args
    # We call a tool that exists (even if it fails later) to check sanitization
    # list_equipment exists in EquipmentHandlerMixin
    
    # We need to mock the handler to avoid complex setup
    from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
    
    # Execute with string "10" for a field that should be int
    result = await handler.execute("list_equipment", {"page": "2", "equipment_type": "chiller"})
    
    # Check tool_usage logs in Skillbook
    with sb.db_path as db: # This is a string, we need to query
        import sqlite3
        with sqlite3.connect(sb.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tool_usage ORDER BY timestamp DESC LIMIT 1").fetchone()
            args = json.loads(row["args"])
            assert isinstance(args["page"], int), f"Page should be int, got {type(args['page'])}"
            print(f"SUCCESS: Type enforcement cast '2' (string) to {args['page']} (int)")

    # --- TEST 3: Observability Tracking ---
    print("\n[Test 3] Observability & Timing...")
    # The previous call to list_equipment should be logged
    import sqlite3
    with sqlite3.connect(sb.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tool_usage WHERE tool_name = 'list_equipment' LIMIT 1").fetchone()
        assert row is not None, "Tool usage should be logged"
        assert row["duration_ms"] > 0, "Duration should be positive"
        print(f"SUCCESS: Tool usage logged. Duration: {row['duration_ms']:.2f}ms")

    # --- TEST 4: Metrics Aggregation ---
    print("\n[Test 4] Tool Metrics Retrieval...")
    metrics = sb.get_tool_metrics("list_equipment")
    assert "list_equipment" in metrics, "Metrics should contain list_equipment"
    print(f"SUCCESS: Metrics retrieved: {metrics['list_equipment']}")

    print("\n" + "="*60)
    print("VERIFICATION COMPLETE: ALL V3 PATTERNS VALIDATED")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_tool_v3())
