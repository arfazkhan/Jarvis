
import asyncio
import os
import sys

# Ensure repo root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_commercial.bms_llm_agent import BMSLLMAgent

async def verify_llm_connection():
    print("Initializing BMSLLMAgent...")
    # Initialize without engines to just test LLM
    try:
        agent = BMSLLMAgent()
        print("Agent initialized.")
    except Exception as e:
        print(f"FAILED to initialize agent: {e}")
        return

    print("Testing LLM connectivity...")
    try:
        # Simple query
        response = await agent.chat("Hello, are you online?")
        # ChatResponse object is returned, we need to check its text property or dict representation
        if hasattr(response, 'text'):
            print(f"Response: {response.text}")
            content = response.text
        else:
            print(f"Response: {response}")
            content = str(response)
        
        if "LLM Error" in content or "Error:" in content:
            print("❌ LLM seems to be FAILING with API Error:")
            print(response)
        else:
            print("✅ LLM seems to be WORKING.")
            
    except Exception as e:
        print(f"❌ LLM Check CRASHED: {e}")

if __name__ == "__main__":
    asyncio.run(verify_llm_connection())
