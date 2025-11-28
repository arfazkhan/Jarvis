import subprocess
import json
from agent.controllers.virtual_device import VirtualMatterDevice

class MatterController:
    def __init__(self, use_virtual=True, arbitration_manager=None):
        self.use_virtual = use_virtual
        self.arbitration_manager = arbitration_manager

        if use_virtual:
            print("[MatterController] Using virtual device")
            self.device = VirtualMatterDevice()
        else:
            print("[MatterController] Using REAL Matter device")
            # Setup anything needed for chip-tool or Python-Matter-SDK initialization
            self.fabric_config = "/path/to/fabric.json"

    # --------------------------
    # DEVICE DISCOVERY
    # --------------------------
    def discover(self):
        """
        Discover Matter devices on the Thread network.
        For now, return simulated data.
        """

        if self.use_virtual:
            return {"switch_1": {"endpoints": list(range(1, 9))}}

        # Real implementation will use:
        # - chip-tool discover commands
        # - or Python Matter SDK APIs

        return {}  # placeholder

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
