import requests
import os
import json
from dotenv import load_dotenv

def main():
    print("⚡ DEBUG: Testing NVIDIA NIM GLM (z-ai/glm4.7) ⚡")
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
    
    # Exact payload from user's curl
    payload = {
        "model": "z-ai/glm4.7",
        "messages": [{"role": "user", "content": "Hello"}], # User had empty string, but some models reject it. Using "Hello" for safety.
        "temperature": 1,
        "top_p": 1,
        "max_tokens": 16384,
        "seed": 42,
        "stream": True,
        "chat_template_kwargs": {
            "enable_thinking": True,
            "clear_thinking": False
        }
    }
    
    print(f"→ Sending request to {url} with model {payload['model']}...")
    try:
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=30)
        print(f"→ Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Receiving Stream:")
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    print(f"   {decoded[:100]}")
        else:
            print(f"❌ Error Body: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    main()
