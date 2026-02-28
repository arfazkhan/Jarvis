import unittest
from unittest.mock import MagicMock, patch
import time
from agent_home.agent_cognitive.meta_agent import MetaAgent
from arvis_core.event_bus.event_bus import EventBus

class TestMetaAgent(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.state_engine = MagicMock()
        self.mission_manager = MagicMock()
        self.safety_validator = MagicMock()
        
        self.meta_agent = MetaAgent(
            self.bus, 
            self.state_engine, 
            self.mission_manager, 
            self.safety_validator,
            check_interval=0.1 # Fast for testing
        )

    def test_initialization(self):
        """Test that MetaAgent initializes correctly."""
        self.assertEqual(self.meta_agent.focus, "idle")
        self.assertEqual(self.meta_agent.urgency, 0.0)
        # Verify subscriptions
        self.assertIn("state_changed", self.bus.subscribers)
        self.assertIn("mission_status_changed", self.bus.subscribers)
        self.assertIn("safety_violation", self.bus.subscribers)

    def test_mission_status_impact(self):
        """Test that mission status updates affect urgency."""
        # 1. Mission Failed -> Urgency Spike
        self.bus.publish({"type": "mission_status_changed", "payload": {"status": "FAILED"}})
        time.sleep(0.1) # Allow event processing
        self.assertEqual(self.meta_agent.urgency, 0.5)
        
        # 2. Another Failure -> More Urgency
        self.bus.publish({"type": "mission_status_changed", "payload": {"status": "FAILED"}})
        time.sleep(0.1)
        self.assertEqual(self.meta_agent.urgency, 1.0)
        
        # 3. Mission Completed -> Urgency Reduction
        self.bus.publish({"type": "mission_status_changed", "payload": {"status": "COMPLETED"}})
        time.sleep(0.1)
        self.assertEqual(self.meta_agent.urgency, 0.8)

    def test_safety_violation(self):
        """Test that safety violations trigger max urgency."""
        self.bus.publish({"type": "safety_violation", "payload": {}})
        time.sleep(0.1)
        
        self.assertEqual(self.meta_agent.focus, "safety_alert")
        self.assertEqual(self.meta_agent.urgency, 1.0)

    def test_proactive_trigger(self):
        """Test that high urgency triggers a proactive suggestion."""
        # Mock the trigger method to verify it's called
        self.meta_agent._trigger_proactive_action = MagicMock()
        
        # Start the loop
        self.meta_agent.start()
        
        # Artificially raise urgency
        self.meta_agent.urgency = 0.9
        
        # Wait for a think cycle
        time.sleep(0.2)
        
        # Verify trigger called
        self.meta_agent._trigger_proactive_action.assert_called()
        
        self.meta_agent.stop()

    def test_proactive_event_publication(self):
        """Test that _trigger_proactive_action publishes an event."""
        # Capture events
        events = []
        self.bus.subscribe("system_notification", lambda e: events.append(e))
        
        self.meta_agent._trigger_proactive_action()
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "system_notification")
        self.assertEqual(events[0]["payload"]["type"], "proactive_suggestion")
        self.assertEqual(self.meta_agent.urgency, 0.0) # Should reset

if __name__ == "__main__":
    unittest.main()
