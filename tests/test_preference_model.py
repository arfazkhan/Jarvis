import unittest
import shutil
from pathlib import Path
from agent_cognitive.preference_model import PreferenceModel

TEST_PREF_PATH = Path("data/test_cognitive/preferences.json")

class TestPreferenceModel(unittest.TestCase):
    def setUp(self):
        if TEST_PREF_PATH.parent.exists():
            shutil.rmtree(TEST_PREF_PATH.parent)
            
        # Similar to ContextGraph, we'll just use the default path for now
        # In a real rigorous test suite, we'd mock the config.
        self.model = PreferenceModel()
        self.model.preferences = {} # Clear state

    def test_explicit_preference(self):
        self.model.set_preference("user_1", "color", "blue")
        val = self.model.get_preference("user_1", "color")
        self.assertEqual(val, "blue")
        
        # Check confidence
        pref = self.model.preferences["user_1"]["color"]
        self.assertEqual(pref["confidence"], 1.0)

    def test_learned_preference(self):
        # Simulate learning
        self.model.learn_from_event("user_1", "set_temperature", {"temperature": 22})
        
        val = self.model.get_preference("user_1", "preferred_temp")
        self.assertEqual(val, 22)
        
        # Check confidence (should be low initially)
        pref = self.model.preferences["user_1"]["preferred_temp"]
        self.assertLess(pref["confidence"], 1.0)
        
        # Reinforce
        self.model.learn_from_event("user_1", "set_temperature", {"temperature": 22})
        new_conf = self.model.preferences["user_1"]["preferred_temp"]["confidence"]
        self.assertGreater(new_conf, pref["confidence"])

if __name__ == "__main__":
    unittest.main()
