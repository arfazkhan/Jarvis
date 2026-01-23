import subprocess
import json
from agent.controllers.virtual_device import VirtualMatterDevice
from agent.config.device_loader import get_device_loader, DeviceConfig

class MatterController:
    def __init__(self, use_virtual=True, arbitration_manager=None, config_path="config/devices.yaml"):
        self.use_virtual = use_virtual
        self.arbitration_manager = arbitration_manager
        
        # Load device configuration from YAML
        self.device_loader = get_device_loader(config_path)
        self.devices = self.device_loader.get_all_devices()

        if use_virtual:
            print(f"[MatterController] Using virtual device ({len(self.devices)} devices from config)")
            self.device = VirtualMatterDevice()
        else:
            print(f"[MatterController] Using REAL Matter device ({len(self.devices)} devices from config)")
            # Setup anything needed for chip-tool or Python-Matter-SDK initialization
            self.fabric_config = "/path/to/fabric.json"

    # --------------------------
    # DEVICE DISCOVERY
    # --------------------------
    def discover(self):
        """
        Discover Matter devices from config.
        Returns dict of device_id -> device info (node_id, endpoints, capabilities).
        """
        if not self.devices:
            # Fallback for empty config
            if self.use_virtual:
                return {"switch_1": {"endpoints": list(range(1, 9))}}
            return {}

        # Build discovery response from YAML config
        discovery = {}
        for device_id, config in self.devices.items():
            discovery[device_id] = {
                "name": config.name,
                "node_id": config.node_id,
                "endpoint": config.endpoint,
                "type": config.type,
                "capabilities": config.capabilities,
                "room": config.room
            }
        
        return discovery
    
    def get_device_config(self, device_id: str) -> DeviceConfig:
        """Get device configuration by ID."""
        return self.device_loader.get_device(device_id)
    
    def resolve_device(self, reference: str):
        """Resolve device reference (name, group, room) to device configs."""
        return self.device_loader.resolve_device_reference(reference)

    # --------------------------
    # TURN ON
    # --------------------------
    def turn_on(self, device_id, endpoint):
        """
        Turns on a relay via Matter.

        If virtual mode is ON:
            - Just toggle virtual relay.
        If real mode:
            - Call chip-tool or Python Matter SDK.
        """

        # Arbitration Check
        if self.arbitration_manager:
            # Default to MISSION_EXECUTION priority if not specified (TODO: Pass priority from caller)
            # For now, we assume standard command
            from agent.agent_core.arbitration_manager import Priority
            # We need a way to know the source/priority. 
            # Ideally, turn_on should accept context.
            # For now, we'll assume a default check, but this is a partial implementation.
            # Real implementation needs source passed down.
            pass

        if self.use_virtual:
            return self.device.turn_on(endpoint)

        # REAL implementation (later)
        # Example using chip-tool:
        # cmd = [
        #     "chip-tool",
        #     "onoff",
        #     "on",
        #     f"{device_id}",
        #     f"{endpoint}",
        #     "--trace_decode", "--timerequest"
        # ]
        # subprocess.run(cmd)

        print(f"[REAL Matter] turn_on() -> device={device_id}, ep={endpoint}")

    # --------------------------
    # TURN OFF
    # --------------------------
    def turn_off(self, device_id, endpoint):
        if self.use_virtual:
            return self.device.turn_off(endpoint)

        # REAL:
        print(f"[REAL Matter] turn_off() -> device={device_id}, ep={endpoint}")
        # subprocess.run([...])

    # --------------------------
    # GET STATE
    # --------------------------
    def get_state(self, device_id):
        if self.use_virtual:
            return self.device.get_state()

        # REAL: Call Matter Read command here
        return {}
