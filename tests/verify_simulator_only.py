
import asyncio
import logging
import json
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

async def test_sim():
    print("Testing LLMEnhancedSimulator isolation...")
    try:
        from agent_advisory.qatar.llm_simulator import LLMEnhancedSimulator
        sim = LLMEnhancedSimulator()
        print("Simulator initialized.")
        
        print("Asking LLM...")
        response = await sim.llm.ask([{"role": "user", "content": "Say 'hello' in JSON format: {'msg': 'hello'}"}])
        print(f"Response: {response.content}")
        
    except Exception as e:
        print(f"CRASH: {e}")

if __name__ == "__main__":
    asyncio.run(test_sim())
