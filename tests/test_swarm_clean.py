import asyncio
import logging
import sys
import os
import traceback
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

# We only want to see the error, disable some noisy loggers
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

from agent_commercial.bms_llm_agent import BMSLLMAgent

async def main():
    with open('/tmp/clean_output.txt', 'w', encoding='utf-8') as f:
        try:
            agent = BMSLLMAgent()
            query = "What is the current status of AHU-01 and are there any alarms on it?"
            f.write("--- SENDING QUERY ---\n")
            response = await agent.chat(query)
            f.write("--- RESPONSE ---\n")
            f.write(response.text + "\n")
        except Exception as e:
            f.write("--- EXCEPTION CAUGHT ---\n")
            f.write(traceback.format_exc() + "\n")

if __name__ == "__main__":
    asyncio.run(main())
