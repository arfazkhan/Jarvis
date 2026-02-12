import asyncio
from agent_unified.tools.bms import BMSToolkit
from agent_unified.agents.manus import ARVISManus
from agent_unified.schema import Message

# Mock Engine Classes
class MockBMSState:
    def get_equipment(self, id): 
        class Eq:
            name="AHU-01"
            eq_type="ahu"
            status="running"
            location="Roof"
        return Eq() if id == "AHU-01" else None
    
    def get_points_by_equipment(self, id):
        class Point:
            point_id="p1"
            name="Temp"
            value=22.5
            unit="C"
        return [Point()]
    
    def get_all_equipment(self):
        class Eq:
            equipment_id="AHU-01"
            eq_type="ahu"
            status="running"
        return [Eq()]

class MockLLM:
    async def ask_tool(self, messages, system_msgs, tools, tool_choice):
        print(f"LLM asked with {len(tools)} tools")
        # Simulate LLM choosing a tool
        from agent_unified.schema import Message, ToolCall, Function
        return Message.assistant_message(
            content="Checking equipment status...",
            tool_calls=[ToolCall(id="call_1", function=Function(name="get_equipment_status", arguments='{"equipment_id": "AHU-01"}'))]
        )

async def test_phase3():
    print("--- Testing BMS Toolkit ---")
    toolkit = BMSToolkit(bms_state=MockBMSState())
    tools = toolkit.get_tools()
    print(f"Tools loaded: {[t.name for t in tools]}")
    assert "get_equipment_status" in [t.name for t in tools]
    
    print("\n--- Testing Agent Tool Execution ---")
    agent = await ARVISManus.create(bms_state=MockBMSState())
    
    # Inject Mock LLM to test tool loop logic without API keys
    agent.llm = MockLLM()
    agent.memory.add_message(Message.user_message("Check AHU-01 status"))
    
    print("Agent Executing Step (Think + Act)...")
    result = await agent.step() 
    
    print(f"Step Result: {result}")
    
    # Verify the tool was executed and returned data
    assert "AHU-01" in result
    assert "running" in result
    assert "get_equipment_status" in result

    
    print("\n✅ Phase 3 Verification Passed!")

if __name__ == "__main__":
    asyncio.run(test_phase3())
