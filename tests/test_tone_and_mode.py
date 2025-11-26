import unittest
from unittest.mock import MagicMock
from agent_sensors.sensor_models import HomeSituation, SleepState, EmotionalState
from agent_personality.mode_switcher import ModeSwitcher
from agent_personality.tone_adapter import ToneAdapter
from agent_personality.persona_profiles import Persona

class TestToneAndMode(unittest.TestCase):

    def test_mode_switcher_overrides(self):
        print("\n[Test] Mode Switcher Overrides")
        switcher = ModeSwitcher()
        user_id = "test_user"
        
        # Default Preference: Jarvis
        switcher.set_user_preference(user_id, "jarvis_style")
        
        # Mock Situation: Normal
        situation = MagicMock(spec=HomeSituation)
        situation.sleep_state = MagicMock(spec=SleepState)
        situation.sleep_state.state = "awake"
        
        emotion = MagicMock(spec=EmotionalState)
        emotion.state = "calm"
        
        # Should be Jarvis
        self.assertEqual(switcher.get_active_persona(user_id, situation, emotion), "jarvis_style")
        
        # Mock Situation: Sleeping (Override)
        situation.sleep_state.state = "sleeping"
        # Should override to Supportive
        self.assertEqual(switcher.get_active_persona(user_id, situation, emotion), "supportive_companion")
        print("✅ Sleep override verified")
        
        # Mock Situation: Stressed (Override)
        situation.sleep_state.state = "awake"
        emotion.state = "stressed"
        # Should override to Supportive
        self.assertEqual(switcher.get_active_persona(user_id, situation, emotion), "supportive_companion")
        print("✅ Stress override verified")

    def test_tone_adapter_styles(self):
        print("\n[Test] Tone Adapter Styles")
        adapter = ToneAdapter()
        
        # Mock Personas
        jarvis = MagicMock(spec=Persona)
        jarvis.id = "jarvis_style"
        jarvis.allowed_features = {"humor": "moderate"}
        
        supportive = MagicMock(spec=Persona)
        supportive.id = "supportive_companion"
        
        neutral = MagicMock(spec=Persona)
        neutral.id = "neutral_assistant"
        
        # Mock Emotion
        calm = MagicMock(spec=EmotionalState)
        calm.state = "calm"
        
        raw_text = "I turned on the lights."
        
        # Jarvis
        res = adapter.adapt_response(raw_text, jarvis, calm)
        self.assertEqual(res, "Activated the lights.")
        
        # Supportive
        res = adapter.adapt_response(raw_text, supportive, calm)
        self.assertEqual(res, "I've turned on the lights.")
        
        # Neutral
        res = adapter.adapt_response(raw_text, neutral, calm)
        self.assertEqual(res, "Turning on the lights.")
        print("✅ Persona styles verified")

    def test_tone_adapter_emotion(self):
        print("\n[Test] Tone Adapter Emotion")
        adapter = ToneAdapter()
        
        jarvis = MagicMock(spec=Persona)
        jarvis.id = "jarvis_style"
        jarvis.allowed_features = {"humor": "moderate"}
        
        raw_text = "Hello."
        
        # Tired
        tired = MagicMock(spec=EmotionalState)
        tired.state = "tired"
        res = adapter.adapt_response(raw_text, jarvis, tired)
        self.assertTrue(res.startswith("(Softly)"))
        
        # Stressed
        stressed = MagicMock(spec=EmotionalState)
        stressed.state = "stressed"
        res = adapter.adapt_response(raw_text, jarvis, stressed)
        self.assertTrue(res.startswith("(Calmly)"))
        print("✅ Emotional prefixes verified")

if __name__ == "__main__":
    unittest.main()
