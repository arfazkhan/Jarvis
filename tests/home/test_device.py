import sys
import os
import time
import yaml
import argparse

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from agent_home.controllers.wifi_controller import WifiController

def load_config():
    try:
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Fallback for testing if run from wrong dir
        try:
            with open("../../config/settings.yaml", "r") as f:
                return yaml.safe_load(f)
        except:
            print("Error: config/settings.yaml not found.")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Device First-Run Test Suite")
    parser.add_argument("device_id", help="Device ID to test")
    args = parser.parse_args()

    print(f"--- Starting Test Suite for: {args.device_id} ---")
    
    config = load_config()
    devices = {d["id"]: d for d in config.get("devices", [])}
    
    if args.device_id not in devices:
        print(f"❌ Error: Device '{args.device_id}' not found in settings.")
        sys.exit(1)

    device = devices[args.device_id]
    controller_type = device.get("controller")
    
    if controller_type != "esphome_http":
        print(f"⚠️  Only 'esphome_http' devices supported in this test script for now.")
        sys.exit(0)

    controller = WifiController()
    endpoint = device.get("endpoint")

    # 1. Ping / Reachability
    print(f"1. Checking Reachability ({endpoint})...", end=" ")
    if controller.get_status(endpoint):
        print("✅ OK")
    else:
        print("❌ FAILED (Device offline?)")
        sys.exit(1)

    # 2. Turn ON
    print("2. Testing TURN ON...", end=" ")
    if controller.turn_on(endpoint):
        print("✅ OK")
    else:
        print("❌ FAILED")

    print("   (Waiting 2 seconds...)")
    time.sleep(2)

    # 3. Turn OFF
    print("3. Testing TURN OFF...", end=" ")
    if controller.turn_off(endpoint):
        print("✅ OK")
    else:
        print("❌ FAILED")

    print("\n✨ Test Complete. Device seems operational.")

if __name__ == "__main__":
    main()
