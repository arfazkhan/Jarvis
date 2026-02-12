import asyncio
from agent_unified.flows.planning import PlanningFlow
from agent_unified.schema import Message
from agent_unified.llm import UnifiedLLM

# Mock LLM that returns a valid plan JSON
class MockPlanningLLM(UnifiedLLM):
    async def ask(self, messages, system_msgs=None, tools=None, tool_choice="auto"):
        content = messages[0]["content"]
        if "Create a step-by-step plan" in content:
            return Message.assistant_message("""
            [
                {"text": "Step 1: Check system status", "depends_on": []},
                {"text": "Step 2: Backup data", "depends_on": [0]}
            ]
            """)
        return Message.assistant_message("Mock response")

class MockAgent:
    async def run(self, text):
        return f"Executed: {text}"

async def test_phase4():
    print("--- Testing Planning Flow ---")
    
    # Initialize Flow with mocks
    flow = PlanningFlow()
    flow.llm = MockPlanningLLM()
    flow.agents = {"arvis": MockAgent()}
    
    print("Executing Plan for: 'Perform system backup'")
    result = await flow.execute("Perform system backup")
    
    print("\n--- Execution Result ---")
    print(result)
    
    assert "Execution Summary" in result
    assert "Step 1: Check system status" in result
    assert "Step 2: Backup data" in result
    assert "2/2 successful" in result
    
    print("\n✅ Phase 4 Verification Passed! (PlanningFlow is functional)")

if __name__ == "__main__":
    asyncio.run(test_phase4())
