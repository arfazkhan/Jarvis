
import asyncio
import logging
from typing import Any, Dict, List
from agent_commercial.tools_schema import BMSToolHandler

# Mock Classes simulating the Scenario adapters
class MockScenarioEnergy:
    def get_summary(self):
        return {"mock_summary": True, "intensity": 100}

class MockScenarioPredictive:
    def predict(self, horizon=24):
        return {"mock_forecast": True, "values": [1, 2, 3]}

class MockEquipment:
    def __init__(self, id, type_val, status_val):
        self.equipment_id = id
        self.equipment_type = type_val # Enum or object with value
        self.status = status_val # Enum or object with value
        self.location = "Building A"
    
    def to_dict(self):
        return {"id": self.equipment_id, "type": str(self.equipment_type), "status": str(self.status)}

class MockEnum:
    def __init__(self, val): self.value = val
    def __str__(self): return self.value

class MockScenarioBMSState:
    async def get_all_equipment(self):
        return [
            MockEquipment("CH-01", MockEnum("chiller"), MockEnum("running")),
            MockEquipment("AHU-01", MockEnum("ahu"), MockEnum("fault"))
        ]

async def test_tools():
    print("Initializing Mock Handler...")
    handler = BMSToolHandler(
        bms_state=MockScenarioBMSState(),
        energy_analyzer=MockScenarioEnergy(),
        predictive_engine=MockScenarioPredictive()
    )
    
    print("\nTesting analyze_energy...")
    # Note: _handle_analyze_energy wraps energy_analyzer.get_summary()
    try:
        res = await handler.execute("analyze_energy", {})
        print(f"Result: {res}")
        if "error" in res: print("FAIL: Error returned")
        elif res.get("mock_summary"): print("PASS: Used injected engine")
        else: print("FAIL: Did not use injected engine")
    except Exception as e:
        print(f"CRASH: {e}")

    print("\nTesting forecast_energy...")
    try:
        res = await handler.execute("forecast_energy", {"forecast_hours": 5})
        print(f"Result: {res}")
        if "error" in res: print("FAIL: Error returned") 
        elif res.get("mock_forecast"): print("PASS: Used injected engine")
        else: print("FAIL: Did not use injected engine")
    except Exception as e:
        print(f"CRASH: {e}")

    print("\nTesting list_equipment...")
    try:
        res = await handler.execute("list_equipment", {})
        print(f"Result: {res}")
        if "error" in res: print("FAIL: Error returned")
        elif res.get("count") == 2: print("PASS: Got equipment list")
        else: print("FAIL: Unexpected result")
    except Exception as e:
        print(f"CRASH: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_tools())
