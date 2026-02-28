import unittest
from unittest.mock import MagicMock, patch
from arvis_core.event_bus.event_bus import EventBus
from agent_conversation.interaction_loop import InteractionLoop
from agent_conversation.dialogue_manager import DialogueManager, DialogueResult

class TestInteractionLoopCore(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.dialogue_manager = MagicMock(spec=DialogueManager)
        self.loop = InteractionLoop(self.event_bus, self.dialogue_manager)
        
    def test_voice_input_flow(self):
        print("\n[Test] Voice Input Flow")
        # Setup mock response
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Hello there",
            should_speak=True
        )
        
        # Subscribe to output
        outputs = []
        self.event_bus.subscribe("voice_response", lambda e: outputs.append(e))
        
        # Publish input
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {"text": "Hi"}
        })
        
        # Verify
        self.dialogue_manager.process_input.assert_called_with("Hi")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["payload"]["text"], "Hello there")
        print("✅ Voice input -> Voice response verified")

    def test_text_input_flow(self):
        print("\n[Test] Text Input Flow")
        # Setup mock response
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Text reply",
            should_speak=True # Should be ignored for text source
        )
        
        outputs = []
        self.event_bus.subscribe("text_response", lambda e: outputs.append(e))
        
        self.event_bus.publish({
            "type": "text_input",
            "payload": {"text": "Hi"}
        })
        
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["payload"]["text"], "Text reply")
        print("✅ Text input -> Text response verified")

    def test_action_request_routing(self):
        print("\n[Test] Action Request Routing")
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Turning it on",
            action_request={"intent": "turn_on", "device": "light"}
        )
        
        actions = []
        self.event_bus.subscribe("action_request", lambda e: actions.append(e))
        
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {"text": "Turn on light"}
        })
        
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["payload"]["intent"], "turn_on")
        print("✅ Action request routing verified")

    def test_mission_command_routing(self):
        print("\n[Test] Mission Command Routing")
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Starting mission",
            mission_command={"command": "start", "mission_id": "security"}
        )
        
        missions = []
        self.event_bus.subscribe("mission_started", lambda e: missions.append(e))
        
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {"text": "Start security"}
        })
        
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0]["payload"]["mission_id"], "security")
        print("✅ Mission command routing verified")

    def test_proactive_notification(self):
        print("\n[Test] Proactive Notification")
        
        voice_outputs = []
        text_outputs = []
        self.event_bus.subscribe("voice_response", lambda e: voice_outputs.append(e))
        self.event_bus.subscribe("text_response", lambda e: text_outputs.append(e))
        
        # 1. High priority -> Voice
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {"message": "Intruder alert", "priority": "high"}
        })
        
        self.assertEqual(len(voice_outputs), 1)
        self.assertEqual(voice_outputs[0]["payload"]["text"], "Intruder alert")
        
        # 2. Normal priority -> Text
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {"message": "Update available", "priority": "normal"}
        })
        
        self.assertEqual(len(text_outputs), 1)
        self.assertEqual(text_outputs[0]["payload"]["text"], "Update available")
        print("✅ Proactive notification verified")

if __name__ == "__main__":
    unittest.main()
