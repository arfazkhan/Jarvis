import unittest
import time
from unittest.mock import MagicMock, patch
from agent.event_bus.event_bus import EventBus
from agent_cognitive.cognitive_loop import CognitiveLoop

class TestCognitiveEnhancements(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.loop = CognitiveLoop(self.bus)
        
    def test_run_cycle_stages(self):
        """Verify run_cycle executes all stages"""
        print("\n[Test] Cognitive Loop Stages")
        
        # Mock methods
        self.loop._check_safety = MagicMock(return_value=[{"type": "safety_alert", "priority": "high"}])
        self.loop._check_maintenance = MagicMock(return_value=[{"type": "maintenance", "priority": "medium"}])
        self.loop.predictor.predict_next_actions = MagicMock(return_value=[{"type": "comfort", "priority": "low", "confidence": 0.9}])
        
        # Capture suggestions
        suggestions = []
        self.bus.subscribe("suggestion", lambda e: suggestions.append(e))
        
        # Run cycle
        self.loop.run_cycle()
        
        # Verify Safety Alert (High Priority)
        self.assertEqual(len(suggestions), 1) # Should only be 1 because safety suppresses others?
        # Wait, my logic was:
        # if safety_alerts: suggestions.extend(safety_alerts)
        # if not safety_alerts: check maintenance...
        
        self.assertEqual(suggestions[0]["payload"]["type"], "safety_alert")
        print("✅ Safety Alert suppressed other stages")
        
        # Test without safety
        self.loop._check_safety.return_value = []
        suggestions = []
        self.loop.run_cycle()
        
        # Should have maintenance + comfort
        self.assertEqual(len(suggestions), 2)
        types = [s["payload"]["type"] for s in suggestions]
        self.assertIn("maintenance", types)
        self.assertIn("comfort", types)
        print("✅ Maintenance and Comfort ran when safe")

if __name__ == "__main__":
    unittest.main()
