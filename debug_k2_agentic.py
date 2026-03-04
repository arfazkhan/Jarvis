import os
import asyncio
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def test_k2_agentic():
    print("⚡ TESTING K2-THINK V2 AGENTIC INTEGRATION ⚡")
    print("============================================")
    
    # Configure Env for the test
    os.environ["LLM_PROVIDER"] = "k2think"
    os.environ["LLM_MODEL"] = "MBZUAI-IFM/K2-Think-v2"
    
    try:
        from agent_unified.llm import UnifiedLLM, _REASONING_AGENT
        
        # Initialize LLM
        llm = UnifiedLLM()
        
        # Re-import to get the initialized global
        from agent_unified.llm import _REASONING_AGENT
        
        if _REASONING_AGENT and _REASONING_AGENT.client:
            # OVERRIDE to the Agentic Endpoint as requested
            _REASONING_AGENT.client.base_url = "https://build-api.k2think.ai/v1"
            print(f"→ Base URL set to: {_REASONING_AGENT.client.base_url}")
        else:
            print("❌ Error: _REASONING_AGENT or client is None")
            return

        # TEST: System Role Support
        print("\n🧪 Test 1: System Role Verification")
        system_msgs = [{"role": "system", "content": "You are a helpful assistant that ONLY speaks in short, punchy rhymes."}]
        messages = [{"role": "user", "content": "What is the agentic capability of K2-Think-v2?"}]
        
        print(f"→ System Prompt: {system_msgs[0]['content']}")
        print(f"→ User Message: {messages[0]['content']}")
        
        print("\n📡 Sending Agentic Request...")
        response = await llm.ask(messages, system_msgs=system_msgs)
        
        print(f"\n✅ Response Received:")
        print("--------------------")
        print(response.content)
        print("--------------------")
        
        if any(char.isupper() for char in response.content): # Basic check for response
            print("\n🎉 Test 1 Success: Agentic endpoint returned a response.")
            # We can check if it followed the rhyme instruction to verify system role support
            print("📝 Check above: Did the model rhyme? If so, system role is supported.")

        # TEST: Tool Calling Support
        print("\n🧪 Test 2: Tool Calling Verification")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        
        messages = [{"role": "user", "content": "What is the weather in Paris?"}]
        print(f"→ Tool defined: get_weather")
        print(f"→ User Message: {messages[0]['content']}")

        print("\n📡 Sending Tool Request...")
        response = await llm.ask(messages, tools=tools)
        
        print(f"\n✅ Response Received:")
        print("--------------------")
        if response.tool_calls:
            print(f"🛠️ Tool Calls Detected: {len(response.tool_calls)}")
            for tc in response.tool_calls:
                print(f"  - Function: {tc.function.name}")
                print(f"  - Arguments: {tc.function.arguments}")
            print("\n🎉 Test 2 Success: K2 correctly identified a tool call!")
        else:
            print("❌ No tool calls detected in response.")
            print("Response Content:")
            print(response.content)
            print("\n📝 Check: Did the model mention calling a tool in text but failed to emit schema?")

        # TEST: Complex Tool Support (ARVIS Style)
        print("\n🧪 Test 3: Complex Tool (ARVIS Style) Verification")
        complex_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_equipment_status",
                    "description": "Get current status of a specific piece of BMS equipment including operational state, data points, and alarms.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "equipment_id": {
                                "type": "string",
                                "description": "Equipment identifier (e.g., 'AHU-01', 'CH-01')"
                            }
                        },
                        "required": ["equipment_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_equipment",
                    "description": "List all BMS equipment, optionally filtered.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "equipment_type": {"type": "string", "description": "Filter by type (ahu, chiller, etc)"},
                            "status": {"type": "string", "description": "Filter by status (running, fault)"}
                        }
                    }
                }
            }
        ]
        
        messages = [{"role": "user", "content": "What is the current status of AHU-ol?"}]
        print(f"→ Complex Tools defined: get_equipment_status, list_equipment")
        print(f"→ User Message: {messages[0]['content']}")

        print("\n📡 Sending Complex Tool Request...")
        response = await llm.ask(messages, tools=complex_tools)
        
        print(f"\n✅ Response Received:")
        print("--------------------")
        if response.tool_calls:
            print(f"🛠️ Tool Calls Detected: {len(response.tool_calls)}")
            for tc in response.tool_calls:
                print(f"  - Function: {tc.function.name}")
                print(f"  - Arguments: {tc.function.arguments}")
            
            # Specific verification for Test 3
            if any(tc.function.name == "get_equipment_status" for tc in response.tool_calls):
                print("\n🎉 Test 3 Success: K2 correctly identified the complex tool and extracted equipment_id!")
            else:
                print("\n❌ Test 3 Failed: K2 called the wrong tool.")
        else:
            print("❌ No tool calls detected in response.")
            print("Response Content:")
            print(response.content)
        
    except Exception as e:
        print(f"❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_k2_agentic())
