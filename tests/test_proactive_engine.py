import unittest
from unittest.mock import MagicMock
import time
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.agent_cognitive.proactive_engine import ProactiveEngine
from agent.event_bus.event_bus import EventBus

class TestProactiveEngine(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.state_engine = MagicMock()
        self.engine = ProactiveEngine(self.bus, self.state_engine)

    def test_bedtime_drift_detection(self):
        """Test detection of late bedtime."""
        # Mock history: 3 nights of late bedtime (2 AM)
        # Timestamps for 2 AM on consecutive days
        base_time = time.time()
        # Align base_time to 2 AM today
        struct = time.localtime(base_time)
        # Reset to 2 AM
        base_ts = time.mktime((struct.tm_year, struct.tm_mon, struct.tm_mday, 2, 0, 0, 0, 0, -1))
        
        history = []
        for i in range(3):
            ts = base_ts - (i * 86400) # Go back i days
            history.append({
                "type": "state_changed",
                "timestamp": ts,
                "payload": {
                    "entity_id": "bedroom_light",
                    "new_state": {"state": "off"}
                }
            })
            
        self.state_engine.get_history.return_value = history
        
        # Capture events
        events = []
        self.bus.subscribe("system_notification", lambda e: events.append(e))
        
        # Run analysis
        self.engine.analyze()
        
        # Verify insight
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["subtype"], "late_bedtime")
        self.assertIn("02:00", events[0]["payload"]["content"])

    def test_no_insight_if_insufficient_data(self):
        """Test that no insight is generated with too little data."""
        history = [{
            "type": "state_changed",
            "timestamp": time.time(),
            "payload": {
                "entity_id": "bedroom_light",
                "new_state": {"state": "off"}
            }
        }]
        self.state_engine.get_history.return_value = history
        
        events = []
        self.bus.subscribe("system_notification", lambda e: events.append(e))
        
        self.engine.analyze()
        
        self.assertEqual(len(events), 0)

if __name__ == "__main__":
    unittest.main()
