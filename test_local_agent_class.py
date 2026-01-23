from agent.llm_agent.local_agent import LocalAgent
import json

def test_local_agent():
    print("Initializing LocalAgent...")
    agent = LocalAgent() # Should find the downloaded model
    
    # Define a simple tool schema
    tools = [
        {
            "name": "turn_on",
            "description": "Turn on a device",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                },
                "required": ["device_id"]
            }
        },
        {
            "name": "escalate",
            "description": "Escalate to superior agent if unsure or complex",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    ]
    
    # Test 1: Simple Command
    print("\n--- Test 1: Simple Command ---")
    user_input = "Turn on device_id kitchen_main"
    print(f"User: {user_input}")
    
    result = agent.generate_tool_call(user_input, tools)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    if result and result[0]['tool'] == 'turn_on':
        print("✅ SUCCESS: Correctly identified turn_on")
    else:
        print("❌ FAILURE: Did not identify turn_on")

    # Test 2: Ambiguous/Complex Command
    print("\n--- Test 2: Complex Command ---")
    user_input = "I'm feeling sad, do something about it"
    print(f"User: {user_input}")
    
    result = agent.generate_tool_call(user_input, tools)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    # We hope for 'escalate' or None (which triggers fallback)
    if result is None or (result and result[0]['tool'] == 'escalate'):
         print("✅ SUCCESS: Correctly escalated or failed")
    else:
         print(f"⚠️ WARNING: Model tried to handle complex query: {result}")

if __name__ == "__main__":
    test_local_agent()
