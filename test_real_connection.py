import asyncio
import os
from dotenv import load_dotenv

# Load env vars first!
load_dotenv()

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

async def test_real_connection():
    print("--- Testing REAL LLM Connection ---")
    
    # Check if keys exist in env
    provider = os.getenv("LLM_PROVIDER", "auto")
    print(f"Configured Provider: {provider}")
    
    keys = [k for k in os.environ.keys() if "API_KEY" in k]
    print(f"Found API Keys: {keys}")
    
    if not keys and provider != "lmstudio":
        print("⚠️ No API keys found! Test might fail.")
    
    print("\nInitializing UnifiedLLM (Real)...")
    llm = UnifiedLLM()
    
    print("Sending request: 'Hello, are you online?'")
    try:
        # Ask a simple question
        response = await llm.ask(
            messages=[{"role": "user", "content": "Hello!"}]
        )
        
        print(f"\n--- RAW RESPONSE CONTENT ---")
        print(repr(response.content))
        print("---------------------------")
        
        if response.content:
            print("\n✅ Real LLM Connection Verified! (Received content)")
        else:
            print("\n⚠️ Received empty content.")
            
    except Exception as e:
        print(f"\n❌ Connection Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_real_connection())
