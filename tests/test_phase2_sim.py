import unittest
import sys
from unittest.mock import MagicMock, patch

# Mock dependencies
mock_groq = MagicMock()
sys.modules["groq"] = mock_groq

from agent.event_bus.event_bus import EventBus
from agent_conversation.dialogue_manager import DialogueManager

class TestPhase2Simulation(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        
        # Setup Groq mock
        self.mock_client = MagicMock()
        mock_groq.Groq.return_value = self.mock_client
        self.mock_completion = MagicMock()
        self.mock_completion.choices[0].message.content = "I am Jarvis."
        self.mock_client.chat.completions.create.return_value = self.mock_completion
        
        with patch.dict("os.environ", {"GROQ_API_KEY": "fake"}):
            self.manager = DialogueManager(self.bus)

    def test_command_flow(self):
        """Test Voice -> Intent -> Action -> TTS"""
        print("\n[Sim] Testing Command Flow...")
        
        # Capture events
        actions = []
        responses = []
        
        self.bus.subscribe("action_request", lambda e: actions.append(e))
        self.bus.subscribe("voice_response", lambda e: responses.append(e))
        
        # Simulate Voice Input (Command)
        self.bus.publish({
            "type": "voice_input",
            "payload": {"text": "Turn on lights in kitchen"}
        })
        
        # Verify Action
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["payload"]["action"], "turn_on")
        self.assertEqual(actions[0]["payload"]["params"]["device"], "lights")
        self.assertEqual(actions[0]["payload"]["params"]["location"], "kitchen")
        print(f"[Sim] Action Verified: {actions[0]['payload']}")
        
        # Verify Response (TTS)
        self.assertEqual(len(responses), 1)
        self.assertIn("Turning on lights", responses[0]["payload"]["text"])
        print(f"[Sim] Response Verified: {responses[0]['payload']['text']}")

    def test_chat_flow(self):
        """Test Voice -> LLM -> TTS"""
        print("\n[Sim] Testing Chat Flow...")
        
        responses = []
        self.bus.subscribe("voice_response", lambda e: responses.append(e))
        
        # Simulate Voice Input (Chat)
        self.bus.publish({
            "type": "voice_input",
            "payload": {"text": "Who are you?"}
        })
        
        # Verify LLM Call
        self.mock_client.chat.completions.create.assert_called()
        
        # Verify Response
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["payload"]["text"], "I am Jarvis.")
        print(f"[Sim] Chat Response Verified: {responses[0]['payload']['text']}")

if __name__ == "__main__":
    unittest.main()
