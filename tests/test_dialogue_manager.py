import unittest
import sys
import time
from unittest.mock import MagicMock, patch

# Mock groq module before importing DialogueManager
mock_groq_module = MagicMock()
sys.modules["groq"] = mock_groq_module

from agent_conversation.dialogue_manager import DialogueManager

class TestDialogueManager(unittest.TestCase):
    def setUp(self):
        self.mock_bus = MagicMock()
        
        # Setup Groq mock
        self.mock_client = MagicMock()
        mock_groq_module.Groq.return_value = self.mock_client
        
        # Mock chat completion
        self.mock_completion = MagicMock()
        self.mock_completion.choices[0].message.content = "Hello human"
        self.mock_client.chat.completions.create.return_value = self.mock_completion

        with patch.dict("os.environ", {"GROQ_API_KEY": "fake_key"}):
            self.manager = DialogueManager(self.mock_bus)

    def test_handle_voice_input(self):
        event = {"payload": {"text": "Hi Jarvis"}}
        
        self.manager.handle_voice_input(event)
        
        # 1. Check history update
        self.assertEqual(len(self.manager.history), 2) # User + Assistant
        self.assertEqual(self.manager.history[0]["content"], "Hi Jarvis")
        self.assertEqual(self.manager.history[1]["content"], "Hello human")
        
        # 2. Check LLM call
        self.mock_client.chat.completions.create.assert_called_once()
        
        # 3. Check TTS event published
        self.mock_bus.publish.assert_called()
        call_args = self.mock_bus.publish.call_args[0][0]
        self.assertEqual(call_args["type"], "voice_response")
        self.assertEqual(call_args["payload"]["text"], "Hello human")

    def test_session_timeout(self):
        # Simulate old interaction
        self.manager.history = [{"role": "user", "content": "old"}]
        self.manager.last_interaction_time = time.time() - 3600 # 1 hour ago
        
        # New input
        event = {"payload": {"text": "New"}}
        self.manager.handle_voice_input(event)
        
        # History should be cleared before adding new
        # So history should contain only "New" and response
        self.assertEqual(self.manager.history[0]["content"], "New")

if __name__ == "__main__":
    unittest.main()
