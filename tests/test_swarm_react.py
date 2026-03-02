import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# Ensure we are in the right directory for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', stream=sys.stdout)
logger = logging.getLogger("test_swarm")

from agent_commercial.bms_llm_agent import BMSLLMAgent

async def main():
    logger.info("Initializing Agent...")
    agent = BMSLLMAgent()
    
    # Give the swarm a query that requires a tool call
    query = "What is the current status of AHU-01 and are there any alarms on it?"
    
    logger.info(f"\nSending Query to Queen: '{query}'")
    response = await agent.chat(query)
    
    logger.info("\n--- FINAL ADVISORY FROM QUEEN ---")
    logger.info(response.text)

if __name__ == "__main__":
    asyncio.run(main())
