import sys
import os
import yaml
import argparse

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.controllers.wifi_controller import WifiController
# from agent.controllers.matter_controller import MatterController # Placeholder

def load_config():
    try:
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("Error: config/settings.yaml not found.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Home Agent CLI Control")
    parser.add_argument("action", choices=["turn_on", "turn_off", "status"], help="Action to perform")
    parser.add_argument("device_id", help="Device ID from settings.yaml")
    args = parser.parse_args()

    config = load_config()
    devices = {d["id"]: d for d in config.get("devices", [])}
    
    if args.device_id not in devices:
        print(f"Error: Device '{args.device_id}' not found in settings.")
        sys.exit(1)

    device = devices[args.device_id]
    controller_type = device.get("controller")

    if controller_type == "esphome_http":
        controller = WifiController()
        endpoint = device.get("endpoint")
        
        if args.action == "turn_on":
            success = controller.turn_on(endpoint)
        elif args.action == "turn_off":
            success = controller.turn_off(endpoint)
        elif args.action == "status":
            alive = controller.get_status(endpoint)
            print(f"Device Reachable: {alive}")
            success = True
            
        if success:
            print(f"SUCCESS: {args.action} {args.device_id}")
        else:
            print(f"FAILED: {args.action} {args.device_id}")
            sys.exit(1)

    elif controller_type == "matter":
        # Check if we should use virtual mode based on settings or default to False for CLI
        # For CLI control, we usually want REAL control unless specified otherwise.
        # But let's respect the global config if possible.
        matter_config = config.get("matter", {})
        # If matter.enabled is False, maybe we shouldn't run? 
        # But let's assume if the device is configured as 'matter', we want to use it.
        
        # We need to determine if we are in simulation mode.
        # The MatterController takes 'use_virtual'. 
        # Let's check a global setting or default to False (Real) for this tool.
        use_virtual = config.get("env", {}).get("mode") != "production"
        
        from agent.controllers.matter_controller import MatterController
        controller = MatterController(use_virtual=use_virtual)
        
        node_id = device.get("node_id")
        endpoint = device.get("endpoint", 1) # Default to endpoint 1
        
        if args.action == "turn_on":
            controller.turn_on(node_id, endpoint)
            print(f"Sent TURN ON to Node {node_id} (EP {endpoint})")
        elif args.action == "turn_off":
            controller.turn_off(node_id, endpoint)
            print(f"Sent TURN OFF to Node {node_id} (EP {endpoint})")
        elif args.action == "status":
            state = controller.get_state(node_id)
            print(f"Device State: {state}")
            
    else:
        print(f"Unknown controller type: {controller_type}")

if __name__ == "__main__":
    main()
