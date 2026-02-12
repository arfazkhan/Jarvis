import asyncio
import os
from dotenv import load_dotenv

# Load env vars first!
load_dotenv()

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

async def test_hybrid_architecture():
    print("--- Testing Hybrid LLM Architecture ---")
    
    print("\n1. Initializing Hybrid LLM...")
    llm = UnifiedLLM()
    
    # 1. Test REASONING (ask) -> Should use K2 Think
    print("\n2. Testing Reasoning Route (ask) -> Expecting K2 Think response...")
    try:
        response = await llm.ask(
            messages=[{"role": "user", "content": "What is 2+2? Explain your thinking."}]
        )
        print(f"\n[Reasoning Response] Content preview: {response.content[:100]}...")
        if response.content:
            print("✅ Reasoning route active.")
    except Exception as e:
        print(f"❌ Reasoning route failed: {e}")

    # 2. Test TOOL EXECUTION (ask_tool) -> Should use Groq
    print("\n3. Testing Tool Route (ask_tool) -> Expecting Groq response...")
    try:
        # Define a mock tool
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
            }
        }]
        
        response = await llm.ask_tool(
            messages=[{"role": "user", "content": "What's the weather in London?"}],
            tools=tools,
            tool_choice="auto"
        )
        
        print(f"\n[Tool Response] Content: {response.content}")
        if response.tool_calls:
            print(f"✅ Tool usage detected: {response.tool_calls[0].function.name}")
        else:
             print("⚠️ No tool call generated (Model might have just chatted)")
             
    except Exception as e:
        print(f"❌ Tool route failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_hybrid_architecture())
