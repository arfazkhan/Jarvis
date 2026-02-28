import requests
import json
import sys

BASE_URL = "http://localhost:8000/api/v1"

def test_scenario():
    print("Testing /sim/scenario...")
    try:
        response = requests.post(
            f"{BASE_URL}/sim/scenario",
            json={"scenario_id": "flash_freeze"},
            timeout=5
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Scenario test failed: {e}")

def test_chat():
    print("\nTesting /chat...")
    try:
        response = requests.post(
            f"{BASE_URL}/chat",
            json={"query": "Status Report"},
            timeout=10
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}...") # Truncate for readability
    except Exception as e:
        print(f"Chat test failed: {e}")

def test_docs():
    print("Testing /api/docs...")
    try:
        response = requests.get(f"http://localhost:8000/api/docs", timeout=5)
        print(f"Status: {response.status_code}")
    except Exception as e:
        print(f"Docs test failed: {e}")

if __name__ == "__main__":
    test_docs()
    test_scenario()
    test_chat()
