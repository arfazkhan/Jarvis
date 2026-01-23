"""Test BMS LLM Agent"""
import asyncio
from agent_bms.bms_llm_agent import BMSLLMAgent

async def test():
    print("Initializing BMS LLM Agent...")
    agent = BMSLLMAgent()
    print(f"Provider: {agent.provider}")
    
    queries = [
        "What's the status of the chillers?",
        "Show me active alarms",
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        response = await agent.chat(query)
        
        print(f"Language: {response.language}")
        print(f"Confidence: {response.confidence}")
        print(f"Tools called: {[tc['tool'] for tc in response.tool_calls]}")
        print(f"\nResponse:\n{response.text[:500] if response.text else 'No response'}")

if __name__ == "__main__":
    asyncio.run(test())
