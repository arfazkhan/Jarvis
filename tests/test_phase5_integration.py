import unittest
from unittest.mock import MagicMock
from agent_sensors.sensor_models import HomeSituation, SleepState, HomePresence, EmotionalState
from agent_personality.safety_policies import SafetyPolicies
from agent_personality.prompt_personality import build_personality_prompt, build_full_system_prompt
from arvis_core.event_bus.event_bus import EventBus
from agent_personality.personality_manager import PersonalityManager

class TestSafetyAndPrompt(unittest.TestCase):

    def test_safety_blocks_inappropriate_content(self):
        print("\n[Test] Safety Blocking")
        safety = SafetyPolicies("config/personality/safety_blocks.yaml")
        
        # Test blocked phrase
        response = "I love you and need you"
        is_safe, redirect = safety.check_response(response)
        self.assertFalse(is_safe)
        self.assertIsNotNone(redirect)
        print("✅ Blocked inappropriate phrase")
        
        # Test medical topic
        response = "You might have a medical diagnosis issue"
        is_safe, redirect = safety.check_response(response)
        self.assertFalse(is_safe)
        self.assertIn("medical", redirect.lower())
        print("✅ Blocked medical content")
        
        # Test safe content
        response = "I turned on the lights"
        is_safe, redirect = safety.check_response(response)
        self.assertTrue(is_safe)
        self.assertIsNone(redirect)
        print("✅ Allowed safe content")

    def test_prompt_personality_generation(self):
        print("\n[Test] Prompt Generation")
        
        # Mock situation
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.sleep_state = MagicMock(spec=SleepState)
        situation.home_presence.state = "home"
        situation.sleep_state.state = "awake"
        situation.activity_hint = "working"
        
        # Mock persona context (Jarvis)
        persona_context = {
            "persona": {
                "id": "jarvis_style",
                "name": "Jarvis",
                "description": "Witty assistant",
                "style_instructions": ["be witty", "be respectful"],
                "allowed_features": {"humor": "moderate", "smalltalk": True, "reflections": True}
            },
            "emotion": {
                "state": "focused",
                "confidence": 0.7
            }
        }
        
        prompt = build_personality_prompt(persona_context, situation)
        
        # Verify key sections
        self.assertIn("PERSONA: Jarvis", prompt)
        self.assertIn("be witty", prompt)
        self.assertIn("focused", prompt)
        self.assertIn("SAFETY CONSTRAINTS", prompt)
        print("✅ Prompt contains persona, emotion, and safety sections")

    def test_end_to_end_personality_flow(self):
        print("\n[Test] End-to-End Personality Integration")
        
        # Setup
        bus = EventBus()
        manager = PersonalityManager(bus)
        safety = SafetyPolicies()
        
        # Mock situation: User sleeping
        situation = MagicMock(spec=HomeSituation)
        situation.home_presence = MagicMock(spec=HomePresence)
        situation.sleep_state = MagicMock(spec=SleepState)
        situation.home_presence.state = "home"
        situation.sleep_state.state = "sleeping"
        situation.activity_hint = "sleeping"
        situation.time_of_day = "night"
        situation.updated_ts = 1000.0
        
        # Get personality context
        context = manager.get_personality_context(situation)
        
        # Verify emotion inference
        self.assertEqual(context["emotion"]["state"], "calm")
        
        # Verify persona override (Jarvis -> Supportive for sleeping)
        self.assertEqual(context["persona"]["id"], "supportive_companion")
        
        # Build prompt
        prompt = build_full_system_prompt(context, situation, base_prompt="Base instructions.")
        self.assertIn("Supportive Companion", prompt)
        self.assertIn("sleeping", prompt.lower())
        
        # Simulate response and apply safety
        raw_response = "I love you, rest well"
        filtered = safety.filter_response(raw_response)
        self.assertNotEqual(filtered, raw_response)  # Should be blocked
        
        print("✅ Full personality flow verified (Emotion -> Mode Switch -> Prompt -> Safety)")

if __name__ == "__main__":
    unittest.main()
