print("DEBUG: Starting test file execution...")
import unittest
from unittest.mock import MagicMock
import time
import os

# Mock EventBus
from arvis_core.event_bus.event_bus import EventBus
from agent_preferences.preference_store import PreferenceStore
from agent_preferences.preference_updater import PreferenceUpdater
from agent_plan.adaptive_plan.adaptive_plan_engine import AdaptivePlanEngine
from agent_feedback.feedback_loop import FeedbackLoop

class TestPhase3Sprint3(unittest.TestCase):
    def setUp(self):
        print("DEBUG: Entering setUp")
        try:
            print("DEBUG: Init EventBus")
            self.event_bus = EventBus()
            print("DEBUG: Init PreferenceStore")
            self.db_path = "test_prefs_sprint3.db"
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            self.store = PreferenceStore(self.db_path)
            print("DEBUG: Init Updater")
            self.updater = PreferenceUpdater(self.store)
            print("DEBUG: Init AdaptiveEngine")
            self.adaptive_engine = AdaptivePlanEngine(self.store)
            print("DEBUG: Init FeedbackLoop")
            self.feedback_loop = FeedbackLoop(self.event_bus, self.updater)
            print("DEBUG: setUp Complete")
        except BaseException as e:
            print(f"DEBUG: setUp Failed: {e}")
            import traceback
            traceback.print_exc()
            import traceback
            traceback.print_exc()
            raise e

    def tearDown(self):
        if hasattr(self, 'db_path') and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except:
                pass

    def test_preference_storage(self):
        """Verify we can store and retrieve preferences"""
        print("\n[Test] Preference Storage")
        self.store.set("lighting", "brightness", 40, 0.8)
        
        pref = self.store.get("lighting", "brightness")
        self.assertIsNotNone(pref)
        self.assertEqual(pref["value"], 40)
        self.assertEqual(pref["confidence"], 0.8)
        print("✅ Stored and retrieved preference")

    def test_adaptive_planning(self):
        """Verify plan adaptation based on preferences"""
        print("\n[Test] Adaptive Planning")
        # 1. Set preference
        self.store.set("lighting", "brightness", 30, 0.9)
        
        # 2. Create raw plan (e.g. from Scene)
        raw_plan = {
            "steps": [
                {"action": "set_light", "params": {"device": "light1", "brightness": 80}}
            ]
        }
        
        # 3. Adapt plan
        adapted_plan = self.adaptive_engine.adapt_plan(raw_plan)
        
        # 4. Verify override
        new_brightness = adapted_plan["steps"][0]["params"]["brightness"]
        self.assertEqual(new_brightness, 30)
        print(f"✅ Adapted brightness from 80 to {new_brightness}")

    def test_feedback_loop_correction(self):
        """Verify learning from user correction"""
        print("\n[Test] Feedback Loop (Correction)")
        
        # 1. Agent executes action
        agent_action = {
            "action": "set_light",
            "params": {"device": "light_living", "brightness": 50}
        }
        self.event_bus.publish({
            "type": "action_execution",
            "payload": {"status": "completed", "action": agent_action}
        })
        
        # 2. User corrects it (changes to 20)
        user_event = {
            "type": "state_change",
            "payload": {
                "source": "user",
                "device_id": "light_living",
                "attribute": "brightness",
                "value": 20
            }
        }
        self.event_bus.publish(user_event)
        
        # 3. Verify preference learned
        # Wait a bit for async? No, EventBus is sync in this implementation.
        
        pref = self.store.get("lighting", "brightness")
        self.assertIsNotNone(pref)
        self.assertEqual(pref["value"], 20)
        # Confidence should be around 0.25 (since old was None/0)
        self.assertTrue(pref["confidence"] > 0.2)
        print(f"✅ Learned preference: {pref}")

if __name__ == "__main__":
    unittest.main()
