import unittest
from unittest.mock import MagicMock
from agent.event_bus.event_bus import EventBus
from agent_conversation.interaction_loop import InteractionLoop
from agent_conversation.dialogue_manager import DialogueManager

class TestInteractionLoopProactive(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.dialogue_manager = MagicMock(spec=DialogueManager)
        self.loop = InteractionLoop(self.event_bus, self.dialogue_manager)
        
    def test_high_priority_notification(self):
        print("\n[Test] High Priority Notification")
        outputs = []
        self.event_bus.subscribe("voice_response", lambda e: outputs.append(e))
        
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {"message": "Fire alarm!", "priority": "high"}
        })
        
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["payload"]["text"], "Fire alarm!")
        print("✅ High priority -> Voice verified")

    def test_normal_priority_notification(self):
        print("\n[Test] Normal Priority Notification")
        outputs = []
        self.event_bus.subscribe("text_response", lambda e: outputs.append(e))
        
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {"message": "System updated", "priority": "normal"}
        })
        
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["payload"]["text"], "System updated")
        print("✅ Normal priority -> Text verified")

    def test_explicit_speak_notification(self):
        print("\n[Test] Explicit Speak Notification")
        outputs = []
        self.event_bus.subscribe("voice_response", lambda e: outputs.append(e))
        
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {"message": "Hello", "speak": True}
        })
        
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["payload"]["text"], "Hello")
        print("✅ Explicit speak -> Voice verified")

if __name__ == "__main__":
    unittest.main()
