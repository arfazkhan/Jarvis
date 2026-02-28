
import unittest
import json
from unittest.mock import MagicMock
from agent_home.learning.reflector import Reflector

class TestReflector(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.reflector = Reflector(self.mock_llm)

    def test_reflection_logic(self):
        """Test that reflector correctly identifies a lesson from history"""
        
        # Scenario: User corrects the agent
        history = [
            {"role": "user", "content": "Turn on the lights"},
            {"role": "agent", "content": "Turning on lights to 100%"},
            {"role": "user", "content": "No, that's too bright. Set them to 50%."},
            {"role": "agent", "content": "Setting lights to 50%."}
        ]
        
        # Mock LLM response to simulate "learning"
        expected_lesson = "When turning on lights, default to 50% brightness unless specified."
        self.mock_llm.generate_tool_calls.return_value = [{
            "tool": "log_lesson",
            "args": {
                "lesson": expected_lesson,
                "context": "User correction on brightness"
            }
        }]
        
        # Run reflection
        tool_calls = self.reflector.reflect(history)
        
        # Verify LLM was called with correct prompt
        self.mock_llm.generate_tool_calls.assert_called_once()
        args = self.mock_llm.generate_tool_calls.call_args
        self.assertIn("Analyze this history", args.kwargs["user_content"])
        self.assertIn("tools", args.kwargs)
        
        # Verify output
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["tool"], "log_lesson")
        self.assertEqual(tool_calls[0]["args"]["lesson"], expected_lesson)
        print("✅ Reflector logic verified with mock LLM.")

if __name__ == '__main__':
    unittest.main()
