import unittest
from unittest.mock import MagicMock
from agent_cognitive.prediction_engine import PredictionEngine

class TestPredictionEngine(unittest.TestCase):
    def setUp(self):
        self.mock_memory = MagicMock()
        self.mock_context = MagicMock()
        self.engine = PredictionEngine(self.mock_memory, self.mock_context)

    def test_predict_by_sequence(self):
        # Mock recent events
        self.mock_memory.get_recent_events.return_value = [
            {"type": "routine_start", "payload": {"name": "movie_mode"}}
        ]
        
        preds = self.engine.predict_next_actions({})
        
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["action"], "turn_off")
        self.assertEqual(preds[0]["device"], "main_lights")
        self.assertGreaterEqual(preds[0]["confidence"], 0.7)

    def test_no_prediction(self):
        # Mock unrelated event
        self.mock_memory.get_recent_events.return_value = [
            {"type": "random_event", "payload": {}}
        ]
        
        preds = self.engine.predict_next_actions({})
        self.assertEqual(len(preds), 0)

if __name__ == "__main__":
    unittest.main()
