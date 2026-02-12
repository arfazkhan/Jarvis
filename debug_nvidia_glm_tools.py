import requests
import os
import json
from dotenv import load_dotenv

def main():
    print("⚡ DEBUG: Testing NVIDIA NIM GLM-4.7 Tool Calling ⚡")
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
                    "unit": {"type": "string", "enum": ["c", "f"]}
                },
                "required": ["location"]
            }
        }
    }]
    
    # Payload with thinking AND tools
    payload = {
        "model": "z-ai/glm4.7",
        "messages": [{"role": "user", "content": "What is the weather in Doha?"}],
        "tools": tools,
        "temperature": 0.5,
        "top_p": 1,
        "max_tokens": 16384,
        "stream": False,
        "chat_template_kwargs": {
            "enable_thinking": True,
            "clear_thinking": False
        }
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
        else:
            print(f"❌ Error Body: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    main()
