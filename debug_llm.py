import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append("e:\\Automation")
load_dotenv()

from agent_unified.llm import UnifiedLLM

async def test_llm():
    print("Testing UnifiedLLM...")
    try:
        llm = UnifiedLLM()
        print(f"Provider: {os.getenv('LLM_PROVIDER')}")
        
        messages = [{"role": "user", "content": "Hello, are you operational?"}]
        print(f"Sending: {messages}")
        
        response = await llm.chat(messages)
        print(f"\nResponse Type: {type(response)}")
        print(f"Response Content: {response.content}")
        print(f"Tool Calls: {response.tool_calls}")
        
        if response.content:
            print("✅ UnifiedLLM functioning.")
        else:
            print("⚠️ UnifiedLLM returned empty content.")
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_llm())
