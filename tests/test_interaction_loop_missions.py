import unittest
from unittest.mock import MagicMock
from agent.event_bus.event_bus import EventBus
from agent_conversation.interaction_loop import InteractionLoop
from agent_conversation.dialogue_manager import DialogueManager, DialogueResult

class TestInteractionLoopMissions(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.dialogue_manager = MagicMock(spec=DialogueManager)
        self.loop = InteractionLoop(self.event_bus, self.dialogue_manager)
        
    def test_start_mission_command(self):
        print("\n[Test] Start Mission Command")
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Starting security mission",
            mission_command={
                "command": "start",
                "mission_id": "home_security",
                "trigger": "voice"
            }
        )
        
        events = []
        self.event_bus.subscribe("mission_started", lambda e: events.append(e))
        
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {"text": "Start security mission"}
        })
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["mission_id"], "home_security")
        self.assertEqual(events[0]["payload"]["trigger"], "voice")
        print("✅ Start mission command verified")

    def test_stop_mission_command(self):
        print("\n[Test] Stop Mission Command")
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Stopping mission",
            mission_command={
                "command": "stop",
                "mission_id": "current"
            }
        )
        
        events = []
        self.event_bus.subscribe("mission_stopped", lambda e: events.append(e))
        
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {"text": "Stop mission"}
        })
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["mission_id"], "current")
        print("✅ Stop mission command verified")

if __name__ == "__main__":
    unittest.main()
