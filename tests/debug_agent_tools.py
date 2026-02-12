
import sys
import os
import asyncio
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from agent_bms.bms_llm_agent import BMSLLMAgent

async def debug_tools():
    agent = BMSLLMAgent()
    
    print(f"Loaded {len(agent.tools)} tools.")
    print("Sample Tool 0:", json.dumps(agent.tools[0], indent=2))
    
    # Test generation
    query = "The chiller is making a loud noise and energy is high."
    print(f"\nQuery: {query}")
    
    # Manually call _generate_tool_calls
    # We need to mock the system prompt or use the real one
    sys_prompt = agent._get_system_prompt("en")
    
    print("\nGenerating tool calls...")
    tool_calls = await agent._generate_tool_calls(sys_prompt, query)
    print("Tool Calls:", tool_calls)

if __name__ == "__main__":
    asyncio.run(debug_tools())
