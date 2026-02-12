import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_unified.llm import UnifiedLLM

async def main():
    print("⚡ DEBUG: Testing NVIDIA NIM Integration ⚡")
    load_dotenv()
    
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("❌ Error: NVIDIA_API_KEY not found in .env")
        return

    print("→ Initializing UnifiedLLM with provider='nvidia'...")
    # Force provider via env var for this test
    os.environ["LLM_PROVIDER"] = "nvidia"
    
    llm = UnifiedLLM()
    
    print("→ Sending test query...")
    print("→ Sending 'Hello' query (Reasoning Agent)...")
    messages = [{"role": "user", "content": "Hello!"}]
    
    try:
        print("→ Sending 'Hello' query (Reasoning Agent)...")
        response = await llm.ask(messages)
        print(f"✅ Response Content:\n{response.content}\n")
        
        print("-" * 50)
        print("→ Testing Tool Call Routing (Tool Agent)...")
        tool_messages = [{"role": "user", "content": "What is the current temperature in the Server Room?"}]
        # Mock tool definition
        tools = [{
            "type": "function",
            "function": {
                "name": "get_bms_value",
                "description": "Get value of a BMS point",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "point_id": {"type": "string"}
                    },
                    "required": ["point_id"]
                }
            }
        }]
        
        response_tool = await llm.ask(tool_messages, tools=tools)
        if response_tool.tool_calls:
            print(f"✅ Tool Response Received (Tool Agent):")
            for tc in response_tool.tool_calls:
                print(f"   🔧 Tool Call: {tc.function.name}({tc.function.arguments})")
        else:
             print(f"   ℹ️ Content (No Tool): {response_tool.content}")
             
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
