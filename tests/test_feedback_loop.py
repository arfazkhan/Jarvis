import unittest
import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.agent_core.state_feedback_loop import StateFeedbackLoop
from agent.event_bus.event_bus import EventBus

class TestStateFeedbackLoop(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.state_engine = MagicMock()
        self.loop = StateFeedbackLoop(self.bus, self.state_engine)

    def test_verification_success(self):
        """Test that matching state triggers verified event."""
        async def run_test():
            # Setup successful state
            self.state_engine.get_state.return_value = "ON"
            
            events = []
            self.bus.subscribe("action_verified", lambda e: events.append(e))
            
            # Simulate action completion
            payload = {
                "step_type": "action",
                "parameters": {
                    "type": "turn_on",
                    "device_id": "light_1"
                }
            }
            
            # Run verification directly (bypassing async sleep for speed if possible, 
            # but we need to await the method)
            await self.loop._verify_action(payload)
            
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["payload"]["actual_state"], "ON")
            
        asyncio.run(run_test())

    def test_verification_failure(self):
        """Test that mismatching state triggers failure event."""
        async def run_test():
            # Setup failed state (remained OFF)
            self.state_engine.get_state.return_value = "OFF"
            
            events = []
            self.bus.subscribe("action_verification_failed", lambda e: events.append(e))
            
            payload = {
                "step_type": "action",
                "parameters": {
                    "type": "turn_on",
                    "device_id": "light_1"
                }
            }
            
            await self.loop._verify_action(payload)
            
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["payload"]["expected"], "ON")
            self.assertEqual(events[0]["payload"]["actual"], "OFF")
            
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
