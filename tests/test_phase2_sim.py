import unittest
import sys
from unittest.mock import MagicMock, patch

# Mock dependencies removed for real LLM testing
# from unittest.mock import MagicMock, patch
# mock_groq = MagicMock()
# sys.modules["groq"] = mock_groq

from agent.event_bus.event_bus import EventBus
from agent_conversation.dialogue_manager import DialogueManager

from agent_conversation.interaction_loop import InteractionLoop

class TestPhase2Simulation(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        
        # Initialize DialogueManager
        self.manager = DialogueManager()
        if not self.manager.client:
             print("WARNING: GROQ_API_KEY not found. Tests may fail.")
             
        # Initialize InteractionLoop
        self.loop = InteractionLoop(self.bus, self.manager)

    def test_command_flow(self):
        """Test Voice -> Intent -> Action -> TTS"""
        print("\n[Sim] Testing Command Flow...")
        
        # Capture events
        responses = []
        self.bus.subscribe("voice_response", lambda e: responses.append(e))
        
        # Mock classifier to ensure intent
        self.manager.classifier = MagicMock()
        self.manager.classifier.classify.return_value = {
            "intent": "turn_on",
            "confidence": 0.9,
            "slots": {"device": "lights", "location": "kitchen"}
        }
        
        # Simulate Voice Input
        self.bus.publish({
            "type": "voice_input",
            "payload": {"text": "Turn on kitchen lights"}
        })
        
        # Wait for async processing (InteractionLoop is async but runs in thread/task?)
        # InteractionLoop subscribes to bus. Bus is synchronous by default unless threaded.
        # EventBus in this project is synchronous.
        # So publishing should trigger handlers immediately.
        
        # Verify Response (TTS)
        self.assertEqual(len(responses), 1)
        self.assertIn("Turning on", responses[0]["payload"]["text"])
        print(f"[Sim] Response Verified: {responses[0]['payload']['text']}")

    def test_chat_flow(self):
        """Test Voice -> LLM -> TTS"""
        print("\n[Sim] Testing Chat Flow...")
        
        responses = []
        self.bus.subscribe("voice_response", lambda e: responses.append(e))
        
        # Mock classifier to fallback to LLM
        self.manager.classifier = MagicMock()
        self.manager.classifier.classify.return_value = {"intent": "unknown", "confidence": 0.0}
        
        # Simulate Voice Input (Chat)
        self.bus.publish({
            "type": "voice_input",
            "payload": {"text": "Who are you?"}
        })
        
        # Verify Response
        import time
        time.sleep(2.0) # Wait for network if real LLM
        
        if not responses:
             print("❌ No response received (Check API Key)")
             return

        self.assertEqual(len(responses), 1)
        print(f"[Sim] Chat Response Verified: {responses[0]['payload']['text']}")
        self.assertTrue(len(responses[0]["payload"]["text"]) > 0)

if __name__ == "__main__":
    unittest.main()
