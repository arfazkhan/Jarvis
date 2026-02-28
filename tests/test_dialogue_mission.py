import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_conversation.dialogue_manager import DialogueManager, DialogueResult
from agent_home.agent_conversation.conversation_bridge import ConversationBridge
from arvis_core.event_bus.event_bus import EventBus

class TestDialogueMissionUnification(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.mission_manager = MagicMock()
        self.dialogue_manager = DialogueManager(mission_manager=self.mission_manager)
        self.bridge = ConversationBridge(self.bus)

    def test_status_query_no_missions(self):
        """Test querying status when no missions are active."""
        self.mission_manager.get_active_missions.return_value = []
        
        # Mock intent classification to return "mission_status"
        self.dialogue_manager.classifier.classify = MagicMock(return_value={
            "intent": "mission_status",
            "confidence": 0.9,
            "slots": {},
            "original_text": "status"
        })
        
        result = self.dialogue_manager.process_input("status")
        
        self.assertIn("no active missions", result.response_text)

    def test_status_query_active_mission(self):
        """Test querying status with an active mission."""
        # Mock active mission
        mission = MagicMock()
        mission.mission_type = "energy_saver"
        mission.status.value = "executing"
        mission.runtime_state = {"step_status": {"s1": "success", "s2": "pending"}}
        
        self.mission_manager.get_active_missions.return_value = [mission]
        
        self.dialogue_manager.classifier.classify = MagicMock(return_value={
            "intent": "mission_status",
            "confidence": 0.9,
            "slots": {},
            "original_text": "status"
        })
        
        result = self.dialogue_manager.process_input("status")
        
        self.assertIn("Energy Saver: EXECUTING", result.response_text)
        self.assertIn("Progress: 1/2", result.response_text)

    def test_bridge_notifications(self):
        """Test that bridge translates mission events to notifications."""
        events = []
        self.bus.subscribe("system_notification", lambda e: events.append(e))
        
        # Simulate mission completed event
        self.bus.publish({
            "type": "mission_execution_completed",
            "payload": {"mission_id": "mission_123"}
        })
        
        # Verify notification
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["type"], "mission_update")
        self.assertIn("Mission mission_123 completed", events[0]["payload"]["content"])

if __name__ == "__main__":
    unittest.main()
