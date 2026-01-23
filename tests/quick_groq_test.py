"""Test REAL Groq tool calling - not just text responses."""
import os
import json
from dotenv import load_dotenv
load_dotenv()

from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Define tools (same format as OpenAI)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "turn_on",
            "description": "Turn on a device",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device to turn on"}
                },
                "required": ["device_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_off",
            "description": "Turn off a device",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device to turn off"}
                },
                "required": ["device_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_brightness",
            "description": "Set brightness level for a light",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100}
                },
                "required": ["device_id", "brightness"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "List all available devices",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# Test commands
commands = [
    "turn on the kitchen light",
    "dim the bedroom light to 50%",
    "what devices do I have?",
]

print("="*70)
print("GROQ TOOL CALLING TEST - REAL FUNCTION CALLS")
print("="*70)

for cmd in commands:
    print(f"\n📋 Command: \"{cmd}\"")
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are ARVIS, a smart home assistant. Use the provided tools to control devices."},
                {"role": "user", "content": cmd}
            ],
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,  # Helps with tool calling reliability
            max_tokens=300
        )
        
        message = response.choices[0].message
        
        # Check if tool calls were made
        if message.tool_calls:
            print(f"🔧 TOOL CALLS: {len(message.tool_calls)}")
            for tc in message.tool_calls:
                print(f"   → {tc.function.name}({tc.function.arguments})")
        else:
            print(f"💬 Text: {message.content[:200] if message.content else 'No content'}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("-"*70)
