import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.agent_feedback.action_tone_adapter import ActionToneAdapter

class TestActionToneAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ActionToneAdapter()

    def test_casual_tone_default(self):
        """Test that default tone is casual."""
        params = {"device": "kitchen light"}
        response = self.adapter.get_confirmation("turn_on", params)
        
        # Casual templates: "Sure thing...", "You got it...", "Lights up!"
        possible_responses = [
            "Sure thing, turning on kitchen light.",
            "You got it, kitchen light on.",
            "Lights up!"
        ]
        self.assertIn(response, possible_responses)

    def test_urgent_tone(self):
        """Test that high urgency triggers urgent tone."""
        params = {"device": "main valve"}
        response = self.adapter.get_confirmation("turn_off", params, urgency=0.9)
        
        # Urgent templates
        possible_responses = [
            "CUTTING POWER to main valve!",
            "Emergency shutdown: main valve."
        ]
        self.assertIn(response, possible_responses)

    def test_missing_params_fallback(self):
        """Test fallback when params are missing."""
        # Template might expect {device}, but we pass empty
        response = self.adapter.get_confirmation("turn_on", {})
        self.assertTrue(len(response) > 0)
        self.assertIn("device", response) # Should use default "device" string

if __name__ == "__main__":
    unittest.main()
