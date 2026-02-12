import requests
import os
import json
from dotenv import load_dotenv

def main():
    print("⚡ DEBUG: Testing NVIDIA Nemotron Native Tool Calling ⚡")
    load_dotenv()
    
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("❌ Error: NVIDIA_API_KEY not found in .env")
        return

    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Simple tool definition
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                },
                "required": ["location"]
            }
        }
    }]
    
    # Payload for Nemotron
    payload = {
        "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "messages": [
            {"role": "system", "content": "/think\nYou are a helpful assistant."},
            {"role": "user", "content": "What is the weather in Doha?"}
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.5,
        "top_p": 1,
        "max_tokens": 1024,
        "stream": False
    }
    
    print(f"→ Sending request to {url} with model {payload['model']}...")
    print(f"→ Tools defined: {len(tools)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        print(f"→ Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Response Body:")
            print(json.dumps(data, indent=2))
            
            # Check for tool calls
            choice = data["choices"][0]
            if choice["message"].get("tool_calls"):
                print("🎉 SUCCESS: Native Tool Call Received!")
                for tc in choice["message"]["tool_calls"]:
                    print(f"   - Function: {tc['function']['name']}")
                    print(f"   - Args: {tc['function']['arguments']}")
            else:
                print("⚠️ No tool call in response.")
        else:
            print(f"❌ Error Body: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    main()
