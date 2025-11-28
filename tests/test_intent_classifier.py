import unittest
from agent_conversation.intent_classifier import IntentClassifier

class TestIntentClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = IntentClassifier()

    def test_turn_on(self):
        text = "Turn on lights in kitchen"
        result = self.classifier.classify(text)
        
        self.assertEqual(result["intent"], "turn_on")
        self.assertEqual(result["slots"]["device"], "lights")
        self.assertEqual(result["slots"]["location"], "kitchen")
        self.assertGreater(result["confidence"], 0.8)

    def test_turn_off_simple(self):
        text = "Turn off TV"
        result = self.classifier.classify(text)
        
        self.assertEqual(result["intent"], "turn_off")
        self.assertEqual(result["slots"]["device"], "tv")

    def test_set_routine(self):
        text = "Activate movie mode"
        result = self.classifier.classify(text)
        
        self.assertEqual(result["intent"], "set_routine")
        self.assertEqual(result["slots"]["routine"], "movie mode")

    def test_unknown(self):
        text = "What is the meaning of life?"
        result = self.classifier.classify(text)
        
        self.assertEqual(result["intent"], "unknown")
        self.assertEqual(result["confidence"], 0.0)

if __name__ == "__main__":
    unittest.main()
