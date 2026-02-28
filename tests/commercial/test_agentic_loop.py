
import sys
import os
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock Dependencies before importing agent
sys.modules["agent_commercial.database"] = MagicMock()
sys.modules["agent_commercial.skillbook"] = MagicMock()
sys.modules["agent_advisory.economy"] = MagicMock()

from agent_commercial.bms_llm_agent import BMSLLMAgent

async def test_agentic_loop():
    print("=== INITIALIZING AGENTIC LOOP TEST ===")
    
    # 1. Setup Mock Agent
    agent = BMSLLMAgent()
    
    # Mock Economy
    agent.economy_policy = MagicMock()
    agent.economy_policy.get_minimal_sufficient_set.return_value = {
        "get_equipment_status", 
        "get_active_alarms", 
        "get_point_history"
    }
    
    # Mock Tool Handler Execution (ASYNC)
    agent.tool_handler = MagicMock()
    agent.tool_handler.execute = AsyncMock()
    
    async def mock_execute(tool_name, args):
        print(f"\n[MOCK TOOL EXEC] {tool_name} called with {args}")
        if tool_name == "get_equipment_status":
            return {"equipment_id": "CHILLER-01", "status": "RUNNING", "vibration": 4.5, "note": "Vibration CRITICAL"}
        elif tool_name == "get_point_history":
            return [{"timestamp": "10:00", "value": 2.1}, {"timestamp": "11:00", "value": 4.5}]
        return {"result": "unknown"}
        
    agent.tool_handler.execute.side_effect = mock_execute
    
    # Mock LLM (ASYNC)
    agent.llm = MagicMock()
    agent.llm.ask_tool = AsyncMock()
    agent.llm.ask = AsyncMock()
    
    # Turn 1: tool call
    msg_1 = MagicMock()
    msg_1.tool_calls = [MagicMock()]
    msg_1.tool_calls[0].function.name = "get_equipment_status"
    msg_1.tool_calls[0].function.arguments = '{"equipment_id": "CHILLER-01"}'
    
    # Turn 2: tool call
    msg_2 = MagicMock()
    msg_2.tool_calls = [MagicMock()]
    msg_2.tool_calls[0].function.name = "get_point_history"
    msg_2.tool_calls[0].function.arguments = '{"point_id": "CHILLER-01/Vibration"}'

    # Turn 3: Final Answer
    msg_3 = MagicMock()
    msg_3.tool_calls = None
    msg_3.content = "I have detected critical vibration on Chiller-01 and historical data shows a spike at 11:00."
    
    # Cycle through responses
    agent.llm.ask_tool.side_effect = [msg_1, msg_2, msg_3]
    agent.llm.ask.return_value = msg_3

    print("=== STARTING CHAT ===")
    try:
        response = await agent.chat("Check Chiller-01 vibration and analyze trends.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return

    print("\n=== VERIFICATION ===")
    print(f"Final Text: {response.text}")
    tool_names = [tc['tool'] for tc in response.tool_calls]
    print(f"Tool Calls Made: {len(response.tool_calls)} -> {tool_names}")
    
    # Verify Grounded Todo List Prompt Injection
    prompt_calls = agent.llm.ask_tool.call_args_list
    grounding_found = False
    citation_found = False
    for call in prompt_calls:
        args, kwargs = call
        messages = kwargs.get('messages', [])
        for m in messages:
            content = m.get('content', '')
            if "Grounded Todo List" in content:
                grounding_found = True
            if "cite the specific evidence" in content:
                citation_found = True
                
    if grounding_found and citation_found:
        print("✅ PASSED: 'Grounded Todo List' & Citation requirements injected.")
    else:
        print(f"❌ FAILED: Grounding={grounding_found}, Citation={citation_found}")

    if len(response.tool_calls) >= 2:
        print("✅ PASSED: Multi-turn execution confirmed.")

if __name__ == "__main__":
    asyncio.run(test_agentic_loop())
