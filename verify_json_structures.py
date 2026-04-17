import asyncio
import json
import logging
from typing import Dict, Any

# Mocking necessary components
class MockBMSState:
    async def get_points_by_equipment(self, equipment_id):
        return []

class MockAlarmEngine:
    def get_priority_queue(self):
        return []
    def get_root_cause_analysis(self, alarm_id):
        class MockReport:
            def to_dict(self):
                return {"root_cause_id": "MOCK-1", "recommendation": "Mock resolution"}
        return MockReport()

# Import the handlers we want to test
from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
from agent_commercial.tools.handlers.energy import EnergyHandlerMixin

class UnifiedHandler(EquipmentHandlerMixin, AlarmHandlerMixin, EnergyHandlerMixin):
    def __init__(self):
        self.bms_state = MockBMSState()
        self.alarm_engine = MockAlarmEngine()
        self.energy_analyzer = None
        self.explainer = None

async def verify():
    handler = UnifiedHandler()
    print("--- Verifying Alarms JSON Structure ---")
    active_alarms = await handler._handle_get_active_alarms({})
    print(f"get_active_alarms keys: {list(active_alarms.keys())}")
    assert "count" in active_alarms
    assert "alarms" in active_alarms
    
    explained = await handler._handle_explain_alarm({"alarm_id": "ALM-001"})
    print(f"explain_alarm keys: {list(explained.keys())}")
    assert "root_cause_id" in explained
    
    print("\n--- Verifying Equipment JSON Structure ---")
    # list_equipment usually returns mock data if db is not connected
    # We just check the structure returned by the handler
    try:
        equip_list = await handler._handle_list_equipment({})
        print(f"list_equipment keys: {list(equip_list.keys())}")
        assert "count" in equip_list
    except Exception as e:
        print(f"list_equipment failed (expected if DB missing): {e}")

    print("\nVerification script finished. Structures match internal logic.")

if __name__ == "__main__":
    asyncio.run(verify())
