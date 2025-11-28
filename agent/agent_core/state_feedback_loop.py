import asyncio
import logging
from typing import Dict, Any

class StateFeedbackLoop:
    """
    Closed-loop intelligence system.
    Verifies that executed actions actually resulted in the expected state changes.
    """
    def __init__(self, event_bus, state_engine):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.logger = logging.getLogger("StateFeedbackLoop")
        
        # Subscribe to completed steps
        self.event_bus.subscribe("mission_step_completed", self._on_step_completed)

    def _on_step_completed(self, event: Dict[str, Any]):
        payload = event.get("payload", {})
        step_type = payload.get("step_type")
        
        # We only verify ACTION steps for now
        if step_type == "action":
            # Run verification in background to allow for settling time
            self._run_async(self._verify_action(payload))

    async def _verify_action(self, payload: Dict[str, Any]):
        """
        Verify the action against the state engine.
        """
        params = payload.get("parameters", {})
        action_name = params.get("action_type") # Assuming action name is here or inferred
        # Wait, MissionStep params usually contain the args for the action.
        # The 'action' name might be implicit or passed differently.
        # In MissionStep, step_type is ACTION, but what is the specific action?
        # Usually params has "type": "turn_on" or similar if using ActionRouter structure.
        # Let's assume params has "type" or "action".
        
        action = params.get("type") or params.get("action")
        device_id = params.get("device_id") or params.get("device")
        
        if not action or not device_id:
            return

        # Wait for state to settle (e.g. propagation delay)
        await asyncio.sleep(2.0)
        
        # Check State
        actual_state = self.state_engine.get_state(device_id)
        expected_state = None
        
        if action == "turn_on":
            expected_state = "ON"
        elif action == "turn_off":
            expected_state = "OFF"
            
        if expected_state:
            # Simple string comparison for MVP. 
            # Real world might need type conversion (bool vs string)
            is_match = str(actual_state).upper() == expected_state
            
            if is_match:
                self.logger.info(f"✅ Verified action {action} on {device_id}: State is {actual_state}")
                self.event_bus.publish({
                    "type": "action_verified",
                    "payload": {
                        "device_id": device_id,
                        "action": action,
                        "actual_state": actual_state
                    }
                })
            else:
                self.logger.warning(f"❌ Verification FAILED for {action} on {device_id}. Expected {expected_state}, got {actual_state}")
                self.event_bus.publish({
                    "type": "action_verification_failed",
                    "payload": {
                        "device_id": device_id,
                        "action": action,
                        "expected": expected_state,
                        "actual": actual_state
                    }
                })

    def _run_async(self, coro):
        """Helper to run coroutine"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass
