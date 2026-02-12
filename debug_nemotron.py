import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

def test_nemotron():
    print("⚡ DEBUG: Testing NVIDIA Nemotron Super 49B ⚡")
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("❌ Error: NVIDIA_API_KEY not found in .env")
        return

    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # As per user request: system msg = /think to trigger reasoning?
    payload = {
        "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "messages": [
            {"role": "system", "content": "/think"},
            {"role": "user", "content": "Why is the sky blue?"}
        ],
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": 1024,
        "stream": False 
    }
    
    print(f"→ Sending request to {url}...")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        print(f"→ Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print("\n✅ Response Content:")
            print(content)
        else:
            print(f"❌ Error: {response.text}")

    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_nemotron()
