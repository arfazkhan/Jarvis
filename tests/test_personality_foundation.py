import unittest
import time
from unittest.mock import MagicMock
from agent.event_bus.event_bus import EventBus
from agent_sensors.sensor_models import HomeSituation, HomePresence, SleepState, EmotionalState
from agent_personality.persona_profiles import PersonaProfiles
from agent_personality.emotion_engine import EmotionEngine
from agent_personality.personality_manager import PersonalityManager

class TestPersonalityFoundation(unittest.TestCase):
    
    def test_persona_loading(self):
        print("\n[Test] Persona Loading")
        profiles = PersonaProfiles("config/personality/personas.yaml")
        
        # Check default
        self.assertEqual(profiles.get_default_persona(), "jarvis_style")
        
        # Check specific persona
        jarvis = profiles.get_persona("jarvis_style")
        self.assertIsNotNone(jarvis)
        self.assertEqual(jarvis.name, "Jarvis")
        self.assertTrue(jarvis.allowed_features["humor"])
        
        # Check neutral
        neutral = profiles.get_persona("neutral_assistant")
        self.assertIsNotNone(neutral)
        self.assertFalse(neutral.allowed_features["humor"])
        print("✅ Personas loaded correctly")

    def test_emotion_inference(self):
        print("\n[Test] Emotion Inference")
        engine = EmotionEngine()
        
        # Mock Situation: Sleeping
        situation = MagicMock(spec=HomeSituation)
        # Mock nested objects
        situation.sleep_state = MagicMock(spec=SleepState)
        situation.home_presence = MagicMock(spec=HomePresence)
        
        situation.sleep_state.state = "sleeping"
        situation.home_presence.state = "home"
        situation.updated_ts = time.time()
        
        emotion = engine.infer_emotion(situation)
        self.assertEqual(emotion.state, "calm")
        self.assertGreaterEqual(emotion.confidence, 0.9)
        
        # Mock Situation: Working
        situation.sleep_state.state = "awake"
        situation.activity_hint = "working"
        situation.time_of_day = "day"
        
        emotion = engine.infer_emotion(situation)
        self.assertEqual(emotion.state, "focused")
        
        # Mock Situation: Away
        situation.home_presence.state = "away"
        emotion = engine.infer_emotion(situation)
        self.assertEqual(emotion.state, "neutral")
        print("✅ Emotion inference logic verified")

    def test_manager_context(self):
        print("\n[Test] Personality Manager Context")
        bus = EventBus()
        manager = PersonalityManager(bus)
        
        # Mock Situation
        situation = MagicMock(spec=HomeSituation)
        situation.sleep_state = MagicMock(spec=SleepState)
        situation.home_presence = MagicMock(spec=HomePresence)
        
        situation.sleep_state.state = "awake"
        situation.activity_hint = "relaxing"
        situation.time_of_day = "evening"
        situation.home_presence.state = "home"
        situation.updated_ts = time.time()
        
        context = manager.get_personality_context(situation)
        
        # Check structure
        self.assertIn("persona", context)
        self.assertIn("emotion", context)
        
        # Check default persona (Jarvis)
        self.assertEqual(context["persona"]["id"], "jarvis_style")
        
        # Check inferred emotion (Relaxing -> Calm)
        self.assertEqual(context["emotion"]["state"], "calm")
        print("✅ Manager integrates persona and emotion")

if __name__ == "__main__":
    unittest.main()
