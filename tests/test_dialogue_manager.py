import unittest
import sys
import time
from unittest.mock import MagicMock, patch

import unittest
import sys
import time
from unittest.mock import MagicMock, patch

# Mock groq module before importing DialogueManager
mock_groq_module = MagicMock()
sys.modules["groq"] = mock_groq_module

from agent_conversation.dialogue_manager import DialogueManager

import importlib
from agent_conversation import dialogue_manager

class TestDialogueManager(unittest.TestCase):
    def setUp(self):
        self.mock_bus = MagicMock()
        
        # Patch get_config to return dicts
        self.config_patcher = patch("config.settings.get_config")
        self.mock_get_config = self.config_patcher.start()
        self.mock_get_config.return_value = {"dialogue": {"session_timeout_minutes": 30}}
        
        # Reload module to pick up new config
        importlib.reload(dialogue_manager)
        from agent_conversation.dialogue_manager import DialogueManager
        
        self.manager = DialogueManager() 
        self.manager.classifier = MagicMock()
        
        print(f"DEBUG: DialogueManager module: {DialogueManager.__module__}")
        import sys
        print(f"DEBUG: sys.modules keys: {[k for k in sys.modules.keys() if 'dialogue_manager' in k]}")
        
    def tearDown(self):
        self.config_patcher.stop()
        
        # Setup Groq mock
        self.mock_client = MagicMock()
        mock_groq_module.Groq.return_value = self.mock_client

    def test_handle_voice_input(self):
        # Setup
        self.manager.classifier.classify.return_value = {
            "intent": "turn_on",
            "confidence": 0.9,
            "slots": {"device": "lights", "location": "kitchen"}
        }
        
        # Execute
        result = self.manager.process_input("Turn on kitchen lights")
        
        # Verify
        self.assertIsNotNone(result.action_request)
        self.assertEqual(result.action_request["intent"], "turn_on")
        self.assertEqual(result.action_request["slots"]["device"], "lights")
        self.assertTrue(result.should_speak)
        
        # Check history
        self.assertEqual(len(self.manager.history), 2)
        self.assertEqual(self.manager.history[0]["content"], "Turn on kitchen lights")

    def test_session_timeout(self):
        # Force DIALOGUE_CONFIG to be a real dict
        import agent_conversation.dialogue_manager
        
        # Simulate old interaction
        self.manager.history = [{"role": "user", "content": "old"}]
        self.manager.last_interaction_time = time.time() - 3600 # 1 hour ago
        
        # Mock classifier to return a known intent
        # This avoids the LLM fallback path entirely, so we don't need to mock the LLM response
        self.manager.classifier.classify.return_value = {
            "intent": "query_status",
            "confidence": 0.9,
            "slots": {"device": "lights"}
        }
        
        # New input
        self.manager.process_input("New")
        
        # History should be cleared before adding new
        self.assertEqual(self.manager.history[0]["content"], "New")

if __name__ == "__main__":
    unittest.main()
