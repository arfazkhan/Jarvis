import os
import asyncio
from dotenv import load_dotenv
from agent_unified.llm import UnifiedLLM

# Load environment
load_dotenv()

async def test_k2():
    print("⚡ TESTING K2-THINK V2 INTEGRATION ⚡")
    print("====================================")
    
    # Configure Env for the test
    os.environ["LLM_PROVIDER"] = "k2think"
    os.environ["K2THINK_MODEL"] = "MBZUAI-IFM/K2-Think-v2"
    
    try:
        from agent_unified.llm import UnifiedLLM, _REASONING_AGENT
        llm = UnifiedLLM() # Ensures initialization runs
        
        # Access the global variable we just imported/initialized
        from agent_unified.llm import _REASONING_AGENT
        if _REASONING_AGENT:
             print(f"→ Base URL: {_REASONING_AGENT.client.base_url}")
        else:
             print("❌ Error: _REASONING_AGENT is None")
             return
        
        messages = [{"role": "user", "content": "Hello, are you v2?"}]
        print(f"→ Sending Request: {messages}")
        
        response = await llm.ask(messages)
        print(f"✅ Response Received:\n{response.content}")
        
    except Exception as e:
        print(f"❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_k2())
