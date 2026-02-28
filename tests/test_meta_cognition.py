
import unittest
import shutil
import tempfile
import os
from datetime import datetime
from agent_cognitive.meta_cognition import MetaCognition, DecisionRecord
from agent_commercial.skillbook import get_skillbook, BuildingSkillbook

class TestMetaCognition(unittest.TestCase):
    def setUp(self):
        # Create a temporary DB
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_skillbook.db")
        
        # Initialize Skillbook with explicit path
        self.skillbook = BuildingSkillbook("test_building", db_path=self.db_path)
        
        # Reset singleton cache
        from agent_commercial.skillbook import _skillbooks
        _skillbooks["test_building"] = self.skillbook
        _skillbooks.clear() # Force clear for safety
        
        # Init MetaCognition
        self.meta = MetaCognition("test_building")
        # Inject our specific skillbook in case singleton logic fought us
        self.meta.skillbook = self.skillbook

    def tearDown(self):
        try:
            # Force close any dangling connections if possible
            import gc
            gc.collect() 
            time.sleep(0.1) # Wait for file release
            shutil.rmtree(self.test_dir)
        except PermissionError:
            print(f"Warning: Could not clean up {self.test_dir} due to file lock")
        except Exception as e:
            print(f"Warning: Cleanup failed: {e}")

    def test_record_decision(self):
        """Test logging a decision."""
        context = {"state": "alarm", "severity": 5}
        d_id = self.meta.record_decision(
            context=context,
            chosen_action="notify",
            alternatives=["wait"],
            confidence=0.9,
            reasoning="High severity"
        )
        
        assert d_id is not None
        
        # Verify persistence
        decisions = self.skillbook.get_recent_decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["decision_id"], d_id)
        self.assertEqual(decisions[0]["chosen_action"], "notify")
        self.assertEqual(decisions[0]["confidence"], 0.9)

    def test_record_outcome(self):
        """Test closing a decision with an outcome."""
        d_id = self.meta.record_decision(
            context={}, chosen_action="act", alternatives=[], confidence=0.8, reasoning="test"
        )
        
        success = self.meta.record_outcome(d_id, outcome="User approved", quality="good")
        self.assertTrue(success)
        
        # Verify
        decisions = self.skillbook.get_recent_decisions()
        self.assertEqual(decisions[0]["outcome"], "User approved")
        self.assertEqual(decisions[0]["outcome_quality"], "good")

    def test_calibration_reflection(self):
        """Test calibration logic."""
        # 1. Create a set of overconfident failures
        for _ in range(5):
            d_id = self.meta.record_decision(
                context={}, chosen_action="fail", alternatives=[], confidence=0.95, reasoning="overconfident"
            )
            self.meta.record_outcome(d_id, outcome="Failed", quality="bad")
            
        # 2. Reflect
        report = self.meta.reflect()
        
        calibration = report.get("calibration", {})
        
        # Should detect overconfidence (high confidence, poor outcomes)
        self.assertEqual(calibration.get("verdict"), "overconfident")
        
        # High bucket error check
        high_bucket = calibration["buckets"]["high"]
        self.assertEqual(high_bucket["count"], 5)
        self.assertEqual(high_bucket["accuracy"], 0.0) # 0 successes

if __name__ == "__main__":
    unittest.main()
