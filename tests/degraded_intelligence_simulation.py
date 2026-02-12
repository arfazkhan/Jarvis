"""
Degraded Intelligence Mode Simulation (Edge Safeties)
=====================================================
Verifies that ARVIS still protects equipment when the LLM is unavailable.
Scenario: Chiller vibration hits critical limits, but the LLM API is down.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.append(os.getcwd())

from agent_bms.bms_llm_agent import BMSLLMAgent, ChatResponse
from agent.memory.orchestrator import MemoryOrchestrator
from agent_cognitive.meta_cognition import MetaCognition

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("degraded_test")

async def run_degraded_test():
    print("🚀 Starting Degraded Intelligence Mode Test...")
    
    # 1. Setup Mock BMS State
    mock_tool_handler = MagicMock()
    
    # Simulate high vibration reading
    async def mock_execute(tool_name, args):
        if tool_name == "get_equipment_status":
            return "Equipment: CHILLER-01 | Status: Running | Vibration: 4.25 mm/s | Eff: 0.82"
        return "Command executed."
        
    mock_tool_handler.execute = mock_execute

    # 2. Setup Memory with a rising trend
    # We need to ensure the TrendEvidenceScore is > 0.3
    memory = MemoryOrchestrator(persist_dir="tests_data/degraded_memories")
    now = datetime.now()
    
    print("   > Seeding 5 days of rising vibration history...")
    for i in range(5):
        timestamp = now - timedelta(days=(5-i))
        obs = f"Day {i+1} Status: Normal. Vibration: {1.2 + (i * 0.5):.2f} mm/s. Efficiency: 0.90."
        memory.remember(obs, "observation", timestamp=timestamp)

    # 3. Instantiate Agent
    agent = BMSLLMAgent()
    agent.tool_handler = mock_tool_handler
    
    # 4. Run the Test Query with Mocked LLM Failures
    print("\n[TEST] Querying agent during LLM outage + Critical Vibration...")
    print("Query: 'What is the current status of the chiller?'")
    
    async def failing_llm(*args, **kwargs):
        raise RuntimeError("LLM API Unavailable (Simulated Outage)")

    with patch('agent_unified.llm.UnifiedLLM.ask', side_effect=failing_llm), \
         patch('agent_unified.llm.UnifiedLLM.ask_tool', side_effect=failing_llm), \
         patch('agent_unified.llm.UnifiedLLM.ask_json', side_effect=failing_llm):
        
        response = await agent.chat("What is the current status of the chiller?")
    
    print("\n--- AGENT RESPONSE (DEGRADED MODE) ---")
    print(f"Text: {response.text}")
    print(f"Confidence: {response.confidence}")
    print(f"Tools Called: {[tc['tool'] for tc in response.tool_calls]}")
    print(f"Sources: {response.sources}")
    
    # 5. Success Criteria
    passed = False
    if "EMERGENCY SHUTDOWN" in response.text and "emergency_shutdown" in [tc['tool'] for tc in response.tool_calls]:
        print("\n✅ PASSED: Agent successfully escalated to Emergency Shutdown via Heuristics.")
        passed = True
    else:
        print("\n❌ FAILED: Agent failed to protect equipment in degraded mode.")
        
    return passed

if __name__ == "__main__":
    asyncio.run(run_degraded_test())
