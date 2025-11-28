import unittest
from unittest.mock import MagicMock, patch
from agent.event_bus.event_bus import EventBus
from agent_conversation.interaction_loop import InteractionLoop
from agent_conversation.dialogue_manager import DialogueManager, DialogueResult

class TestPhase10Rigorous(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.dialogue_manager = MagicMock(spec=DialogueManager)
        self.loop = InteractionLoop(self.event_bus, self.dialogue_manager)
        
    def test_dialogue_manager_error_handling(self):
        print("\n[Test] Dialogue Manager Error Handling")
        # DM raises exception
        self.dialogue_manager.process_input.side_effect = Exception("DM Crash")
        
        # Should not crash the loop/event bus
        try:
            self.event_bus.publish({
                "type": "voice_input",
                "payload": {"text": "Hello"}
            })
            print("✅ Loop survived DM crash")
        except Exception as e:
            self.fail(f"Loop crashed: {e}")

    def test_malformed_payloads(self):
        print("\n[Test] Malformed Payloads")
        # 1. Missing text
        self.event_bus.publish({
            "type": "voice_input",
            "payload": {} 
        })
        self.dialogue_manager.process_input.assert_not_called()
        
        # 2. None payload
        self.event_bus.publish({
            "type": "voice_input",
            "payload": None
        })
        self.dialogue_manager.process_input.assert_not_called()
        print("✅ Malformed payloads handled gracefully")

    def test_complex_mission_flow(self):
        print("\n[Test] Complex Mission Flow")
        # Sequence: Start -> Status -> Stop
        
        # 1. Start
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Starting",
            mission_command={"command": "start", "mission_id": "m1"}
        )
        
        mission_events = []
        self.event_bus.subscribe("mission_started", lambda e: mission_events.append(e))
        self.event_bus.subscribe("mission_stopped", lambda e: mission_events.append(e))
        
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "Start m1"}})
        
        self.assertEqual(len(mission_events), 1)
        self.assertEqual(mission_events[0]["type"], "mission_started")
        
        # 2. Status (Text only response)
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Running",
            mission_command={"command": "status"}
        )
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "Status"}})
        
        # 3. Stop
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="Stopping",
            mission_command={"command": "stop", "mission_id": "m1"}
        )
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "Stop m1"}})
        
        self.assertEqual(len(mission_events), 2)
        self.assertEqual(mission_events[1]["type"], "mission_stopped")
        print("✅ Complex mission flow verified")

    def test_llm_fallback_integration(self):
        print("\n[Test] LLM Fallback Integration")
        # Simulate DM returning text from LLM (no action/mission)
        self.dialogue_manager.process_input.return_value = DialogueResult(
            response_text="This is an LLM response",
            should_speak=True
        )
        
        voice_outputs = []
        self.event_bus.subscribe("voice_response", lambda e: voice_outputs.append(e))
        
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "Tell me a joke"}})
        
        self.assertEqual(len(voice_outputs), 1)
        self.assertEqual(voice_outputs[0]["payload"]["text"], "This is an LLM response")
        print("✅ LLM fallback response routed correctly")

    def test_concurrent_inputs(self):
        print("\n[Test] Concurrent Inputs")
        # Simulate burst of inputs
        # EventBus is synchronous, so they process sequentially, but we verify order/handling
        
        self.dialogue_manager.process_input.side_effect = [
            DialogueResult(response_text="R1"),
            DialogueResult(response_text="R2"),
            DialogueResult(response_text="R3")
        ]
        
        outputs = []
        self.event_bus.subscribe("voice_response", lambda e: outputs.append(e["payload"]["text"]))
        
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "1"}})
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "2"}})
        self.event_bus.publish({"type": "voice_input", "payload": {"text": "3"}})
        
        self.assertEqual(outputs, ["R1", "R2", "R3"])
        print("✅ Concurrent inputs processed sequentially")

if __name__ == "__main__":
    unittest.main()
