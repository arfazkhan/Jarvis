import asyncio
import os
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_bms.bms_llm_agent import BMSLLMAgent
from tests.super_gauntlet import MockBMSState, MockAlarmEngine, MockEnergyAnalyzer, MockPredictiveEngine

async def test_memory_injection():
    print("Testing Titan Memory Injection to Prompt...")
    
    # Initialize mocks
    mock_state = MockBMSState()
    mock_alarm = MockAlarmEngine()
    mock_energy = MockEnergyAnalyzer()
    mock_pm = MockPredictiveEngine()
    
    agent = BMSLLMAgent(
        bms_state=mock_state,
        alarm_engine=mock_alarm,
        energy_analyzer=mock_energy,
        predictive_engine=mock_pm
    )
    
    # Day 1: Make a recommendation
    print("\n[Day 1] Prompting agent...")
    query1 = "Chiller 1 is vibrating. What should I do?"
    resp1 = await agent.chat(query1)
    print(f"Agent Action: {resp1.text[:50]}...")
    
    # Check if tracker recorded it
    recent = agent.tracker.get_recent_recommendations(window_days=1)
    print(f"Tracker entries: {len(recent)}")
    if recent:
        print(f"Logged Action: {recent[0].recommended_action.get('action')}")
    
    # Day 2: See if Day 1 is in prompt
    print("\n[Day 2] Checking prompt construction...")
    # We call the internal method to see the prompt
    prompt = await agent._get_system_prompt("Checking status.", "en")
    
    # Debug: Print first 1000 chars of prompt to see structure
    print("-" * 40)
    print("PROMPT PREVIEW (FIRST 1000 CHARS):")
    print(prompt[:1000])
    print("-" * 40)

    # Specific check for history summary
    import re
    history_match = re.search(r"### Trend Facts\s*(.*?)\s*###", prompt, re.DOTALL)
    if history_match:
        content = history_match.group(1).strip()
        print(f"DEBUG: Found History Summary: '{content}'")
        if "Chiller" in content or "Schedule" in content:
            print("✅ SUCCESS: Previous context found in history summary!")
        else:
            print("❌ FAILURE: History summary is empty or doesn't match.")
    else:
        print("❌ FAILURE: History summary section NOT FOUND in prompt.")

    # Check for calibration section
    if "META-COGNITIVE OVERRIDES" in prompt:
        print("✅ SUCCESS: ACE Calibration section found!")
    else:
        print("❌ FAILURE: ACE Calibration section NOT FOUND.")

if __name__ == "__main__":
    asyncio.run(test_memory_injection())
