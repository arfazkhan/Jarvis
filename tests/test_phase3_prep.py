import unittest
import time
import queue
import json
from unittest.mock import MagicMock, patch
import os

from agent.event_bus.event_bus import EventBus
from agent_cognitive.cognitive_loop import CognitiveLoop
from agent_cognitive.context_graph import ContextGraph
from agent_conversation.dialogue_manager import DialogueManager

class TestPhase3Prep(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def test_async_cognitive_loop(self):
        """Verify CognitiveLoop uses queue and doesn't block"""
        print("\n[Test] Async Cognitive Loop")
        loop = CognitiveLoop(self.bus)
        
        # Publish event
        start_time = time.time()
        self.bus.publish({"type": "test_event", "payload": {}})
        duration = time.time() - start_time
        
        # Should be instant (just queue put)
        self.assertLess(duration, 0.01)
        
        # Verify it's in queue
        self.assertFalse(loop.event_queue.empty())
        item = loop.event_queue.get()
        self.assertEqual(item["type"], "test_event")
        print("✅ CognitiveLoop is async (Queue used)")

    def test_context_graph_ttl(self):
        """Verify Context Graph TTL and cleanup"""
        print("\n[Test] Context Graph TTL")
        graph = ContextGraph()
        graph.clear()
        
        # Add edge with short TTL (0.1s)
        graph.add_edge("user", "cooking", "is_doing", ttl=0.1)
        self.assertTrue(graph.graph.has_edge("user", "cooking"))
        
        # Wait for expiration
        time.sleep(0.2)
        
        # Cleanup
        graph.cleanup_expired_edges()
        
        # Verify removal
        self.assertFalse(graph.graph.has_edge("user", "cooking"))
        print("✅ Context Graph TTL works (Edge expired)")

    def test_structured_llm_output(self):
        """Verify DialogueManager handles JSON from LLM"""
        print("\n[Test] Structured LLM Output")
        
        # Mock Groq response with JSON
        with patch("agent_conversation.dialogue_manager.Groq") as MockGroq:
            mock_client = MagicMock()
            MockGroq.return_value = mock_client
            mock_completion = MagicMock()
            mock_completion.choices[0].message.content = '{"intent": "party_mode", "steps": ["music", "lights"]}'
            mock_client.chat.completions.create.return_value = mock_completion
            
            with patch.dict("os.environ", {"GROQ_API_KEY": "fake"}):
                dm = DialogueManager(self.bus)
                # Mock classifier to force LLM path
                dm.classifier = MagicMock()
                dm.classifier.classify.return_value = {"intent": "unknown", "confidence": 0.0}
                
                # Capture actions
                actions = []
                self.bus.subscribe("action_request", lambda e: actions.append(e))
                
                # Simulate complex request
                self.bus.publish({
                    "type": "voice_input",
                    "payload": {"text": "Get ready for a party"}
                })
                
                # Verify action request generated from JSON
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0]["payload"]["intent"], "party_mode")
                self.assertEqual(actions[0]["payload"]["target"], "complex_plan")
                print("✅ DialogueManager parsed JSON from LLM")

if __name__ == "__main__":
    unittest.main()
