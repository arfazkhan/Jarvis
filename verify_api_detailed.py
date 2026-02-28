import requests
import json
import time

BASE_URL = "http://localhost:8000/api/v1"

def print_json(data):
    print(json.dumps(data, indent=2))

def capture_demo_flow():
    results = {}
    
    # 1. Dashboard Overview (Control Status)
    print("\n--- 1. Simulation Control (Status Check) ---")
    try:
        # Pinging control to see current state (hacky, but valid)
        resp = requests.post(f"{BASE_URL}/sim/control", json={"action": "SET_MANUAL", "enabled": True})
        results["control_status"] = resp.json()
        print_json(results["control_status"])
    except Exception as e:
        print(f"Control check failed: {e}")

    # 2. Set Scenario
    print("\n--- 2. Set Scenario (Flash Freeze) ---")
    try:
        resp = requests.post(f"{BASE_URL}/sim/scenario", json={"scenario_id": "flash_freeze"})
        results["set_scenario"] = resp.json()
        print_json(results["set_scenario"])
    except Exception as e:
        print(f"Scenario set failed: {e}")

    # 3. Equipment Override
    print("\n--- 3. Equipment Override (Chiller-01 OFF) ---")
    try:
        resp = requests.post(f"{BASE_URL}/simulation/equipment/override", json={"equipment_id": "CHILLER-01", "value": False})
        results["override"] = resp.json()
        print_json(results["override"])
    except Exception as e:
        print(f"Override failed: {e}")

    # 4. Chat Interaction
    print("\n--- 4. Chat Interaction (Status Report) ---")
    try:
        start_time = time.time()
        resp = requests.post(f"{BASE_URL}/chat", json={"query": "Status Report"}, timeout=30)
        results["chat"] = resp.json()
        duration = time.time() - start_time
        results["chat"]["_latency_seconds"] = round(duration, 2)
        print_json(results["chat"])
    except Exception as e:
        print(f"Chat failed: {e}")

    # Write strictly to file to avoid terminal truncation
    with open("api_verification_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to api_verification_results.json")

if __name__ == "__main__":
    capture_demo_flow()
