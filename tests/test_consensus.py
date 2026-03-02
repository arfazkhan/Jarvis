import asyncio
import logging
import sys
import os
import traceback
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

from agent_commercial.bms_llm_agent import BMSLLMAgent

async def main():
    with open('/tmp/consensus_test.txt', 'w', encoding='utf-8') as f:
        try:
            agent = BMSLLMAgent()
            # Actionable query designed to trigger 1) Proposer phase, 2) BFT Quorum vote
            query = "We need to save power. Please optimize AHU-01 and reduce its fan speed by 50% immediately."
            f.write("--- SENDING ACTIONABLE QUERY ---\n")
            f.write(f"{query}\n")
            
            response = await agent.chat(query)
            
            f.write("\n--- FINAL ARVIS ADVISORY ---\n")
            f.write(response.text + "\n")
            
        except Exception as e:
            f.write("--- EXCEPTION CAUGHT ---\n")
            f.write(traceback.format_exc() + "\n")

if __name__ == "__main__":
    asyncio.run(main())
