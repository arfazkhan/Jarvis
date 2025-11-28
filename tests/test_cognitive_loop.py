import unittest
import time
from unittest.mock import MagicMock
from agent_cognitive.cognitive_loop import CognitiveLoop

class TestCognitiveLoop(unittest.TestCase):
    def setUp(self):
        self.mock_bus = MagicMock()
        self.loop = CognitiveLoop(self.mock_bus)
        
        # Mock internal components to avoid DB/File I/O
        self.loop.memory = MagicMock()
        self.loop.context = MagicMock()
        self.loop.predictor = MagicMock()

    def test_event_handling(self):
        event = {"type": "test", "payload": {}}
        self.loop._on_event(event)
        self.loop._process_queue()
        
        # Should store in memory
        self.loop.memory.add_event.assert_called_with(event)

    def test_location_update(self):
        event = {
            "type": "location_change",
            "payload": {"user_id": "u1", "location": "kitchen"}
        }
        self.loop._on_event(event)
        self.loop._process_queue()
        
        # Should update context
        self.loop.context.add_edge.assert_called_with("u1", "kitchen", "is_in")

    def test_run_cycle(self):
        # Mock prediction
        self.loop.predictor.predict_next_actions.return_value = [
            {"action": "test", "confidence": 0.9}
        ]
        
        self.loop.run_cycle()
        
        # Should publish suggestion
        self.mock_bus.publish.assert_called()
        call_args = self.mock_bus.publish.call_args[0][0]
        self.assertEqual(call_args["type"], "suggestion")
        self.assertEqual(call_args["payload"]["action"], "test")

if __name__ == "__main__":
    unittest.main()
