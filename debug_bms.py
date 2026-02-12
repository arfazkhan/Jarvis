"""
Curl-equivalent test for K2 API with streaming
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("K2THINK_API_KEY")
if not api_key:
    print("ERROR: No K2THINK_API_KEY")
    exit(1)

url = "https://api.k2think.ai/v2/chat/completions"
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": "MBZUAI-IFM/K2-Think",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": True  # Adding stream=true as in user's curl
}

print(f"DEBUG: Sending to {url}")
print(f"DEBUG: Payload: {payload}")

try:
    # Use stream=True in httpx for streaming response
    with httpx.stream("POST", url, headers=headers, json=payload, timeout=30) as response:
        print(f"DEBUG: Status: {response.status_code}")
        for chunk in response.iter_text():
            print(chunk, end="")
except Exception as e:
    print(f"DEBUG: Error: {e}")
