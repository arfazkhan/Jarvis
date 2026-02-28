import asyncio
import os
import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment for API keys
from dotenv import load_dotenv
load_dotenv()

# We need to explicitly check for API keys to avoid silent failures
REQUIRED_KEYS = ["GROQ_API_KEY", "OPENAI_API_KEY"]
missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
if missing:
    print(f"⚠️ Warning: Missing API keys: {missing}. Test may fail if these providers are used.")

from agent_unified.llm import UnifiedLLM
from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.base import BaseTool, ToolResult
from agent_unified.tools.collection import ToolCollection
from agent_unified.schema import Message
from agent_commercial.tools import BMSToolHandler, get_all_tools
from agent_commercial.skillbook import BuildingSkillbook

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_tool_v3_llm")

class BMSToolAdapter(BaseTool):
    """Adapter to wrap a modular BMS Tool into ARVISToolAgent's BaseTool."""
    # We use PrivateAttr since Pydantic might complain about arbitrary types
    # But BaseTool Config allows arbitrary types
    handler: BMSToolHandler
    
    async def execute(self, **kwargs) -> ToolResult:
        try:
            logger.info(f"Executing BMS Tool: {self.name} with args: {kwargs}")
            result = await self.handler.execute(self.name, kwargs)
            
            if isinstance(result, dict) and "error" in result:
                # Return structured error back to LLM as a JSON string
                # This allows the LLM to see the 'recovery_hint'
                return ToolResult(error=json.dumps(result["error"]))
                
            # Handle non-serializable objects (like Skill dataclasses) by converting to dict
            def serialize_bms_result(obj):
                if hasattr(obj, "to_dict"):
                    return obj.to_dict()
                if isinstance(obj, (list, tuple)):
                    return [serialize_bms_result(i) for i in obj]
                if isinstance(obj, dict):
                    return {k: serialize_bms_result(v) for k, v in obj.items()}
                return obj

            serialized_result = serialize_bms_result(result)
            return ToolResult(output=json.dumps(serialized_result, indent=2))
        except Exception as e:
            logger.exception(f"Exception executing {self.name}")
            return ToolResult(error=str(e))

class MockBMSState:
    async def get_equipment(self, equipment_id):
        # Lambda must accept 'self' argument when called as an instance method
        return type('Eq', (), {'to_dict': lambda s: {"id": equipment_id, "type": "AHU", "status": "running"}})()
    async def get_points_by_equipment(self, equipment_id):
        return []

async def test_tool_v3_llm():
    print("\n" + "="*60)
    print("ARVIS TOOL V3 RED/GREEN LLM INTEGRATION TEST")
    print("="*60)
    
    # 1. Setup Skillbook
    # Using a fresh DB for this test
    # Clean up if exists
    if os.path.exists("test_v3_llm.db"):
        os.remove("test_v3_llm.db")
        
    sb = BuildingSkillbook(building_id="real_llm_test", db_path="test_v3_llm.db")
    
    # Add a mock skill to the skillbook to test retrieval
    await sb.add_skill(
        title="AHU-01 Power Quirk",
        equipment_id="AHU-01",
        description="AHU-01 shows high power consumption when the chilled water valve is stuck at 100%. Check valve position.",
        skill_type="equipment_quirk"
    )
    
    # 2. Setup Handler with Mock BMS
    handler = BMSToolHandler(knowledge_base=sb, bms_state=MockBMSState())
    
    # 3. Create Tool Collection from Definitions
    collection = ToolCollection()
    all_definitions = get_all_tools()
    
    print(f"Loading {len(all_definitions)} tool definitions into collection...")
    for definition in all_definitions:
        tool = BMSToolAdapter(
            name=definition["name"],
            description=definition["description"],
            parameters=definition.get("parameters", {"type": "object", "properties": {}}),
            handler=handler
        )
        collection.add_tools(tool)
        
    # 4. Initialize Agent
    llm = UnifiedLLM()
    # ARVISToolAgent is a Pydantic model. We'll use a simple wrapper or set attribute carefully.
    agent = ARVISToolAgent(
        name="ARVIS_V3_Tester",
        available_tools=collection,
        system_prompt=(
            "You are ARVIS, a professional BMS Operations Copilot. "
            "Your goal is to diagnose building issues with surgical precision. "
            "Use tools efficiently. Follow the examples provided in tool parameters for formatting IDs. "
            "If a tool returns an error with a recovery_hint, use that hint to fix your next call."
        )
    )
    # Use object.__setattr__ to bypass Pydantic validation for the test
    object.__setattr__(agent, 'llm', llm)
    
    # 5. Execute COMPLEX SCENARIO
    print("\n[Scenario] Diagnosing AHU-01 Power Anomaly")
    print("-" * 60)
    
    # Prompt designed to trigger multiple V3 capabilities:
    # - get_equipment_status (Surgical ID)
    # - query_skillbook (Memory Bridge)
    # - simulate_change (Planning with Uncertainty)
    prompt = """
    A facility manager reports that 'AHU-01 is consuming too much power'. 
    
    Please perform the following steps:
    1. Check its current status (use the correct equipment ID).
    2. Query the Skillbook for any known quirks or patterns for AHU-01.
    3. If there's a quirk mentioned, simulate a 'setpoint_adjustment' to 23.0 to see the predicted impact on energy and comfort.
    4. Provide a final verified recommendation based on the simulation and quirks.
    """
    
    # Add initial message
    agent.memory.add_message(Message.user_message(prompt))
    
    # RUN LOOP (Think -> Act)
    # We'll run up to 4 iterations
    for i in range(4):
        print(f"\n[Turn {i+1}] Thinking...")
        try:
            has_tool_calls = await agent.think()
            
            if not has_tool_calls:
                print("[Agent] No more tools. Finalizing response...")
                break
                
            print(f"[Agent] Planned tools: {[tc.function.name for tc in agent.tool_calls]}")
            for tc in agent.tool_calls:
                print(f"  -> {tc.function.name}({tc.function.arguments})")
                
            actions_summary = await agent.act()
            print(f"[Agent] Turn {i+1} execution complete.")
            
        except Exception as e:
            print(f"⚠️ Error during agent loop: {e}")
            break
            
    print("\n" + "="*60)
    print("FINAL RESPONSE")
    print("-" * 60)
    if agent.memory.messages:
        print(agent.memory.messages[-1].content)
    else:
        print("No response generated.")
    print("="*60)
    
    # 6. Verify Observability in Skillbook
    print("\n[Observability Metrics]")
    # We use sb directly since it's the live instance
    try:
        metrics = sb.get_tool_metrics()
        if metrics:
            print(json.dumps(metrics, indent=2))
        else:
            print("No metrics recorded in database.")
    except Exception as me:
        print(f"Failed to fetch metrics: {me}")

if __name__ == "__main__":
    asyncio.run(test_tool_v3_llm())
