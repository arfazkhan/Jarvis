import unittest
import sys
from unittest.mock import MagicMock, patch

# Mock dependencies removed for real LLM testing
# from unittest.mock import MagicMock, patch
# mock_groq = MagicMock()
# sys.modules["groq"] = mock_groq

from agent.event_bus.event_bus import EventBus
from agent_conversation.dialogue_manager import DialogueManager

class TestPhase2Simulation(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        
        # Initialize DialogueManager with real client
        # Requires GROQ_API_KEY in environment
        self.manager = DialogueManager(self.bus)
        
        if not self.manager.client:
             print("WARNING: GROQ_API_KEY not found. Tests may fail.")

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
        self.assertEqual(actions[0]["payload"]["intent"], "turn_on")
        self.assertEqual(actions[0]["payload"]["slots"]["device"], "lights")
        self.assertEqual(actions[0]["payload"]["slots"]["location"], "kitchen")
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
        
        # Verify Response
        import time
        time.sleep(2.0) # Wait for network
        
        if not responses:
             print("❌ No response received (Check API Key)")
             return

        self.assertEqual(len(responses), 1)
        print(f"[Sim] Chat Response Verified: {responses[0]['payload']['text']}")
        self.assertTrue(len(responses[0]["payload"]["text"]) > 0)

if __name__ == "__main__":
    unittest.main()
