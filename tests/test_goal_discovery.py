
import unittest
import time
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from agent_advisory.goal_generator import GoalDiscoveryEngine, ProactiveGoal

class TestGoalDiscoveryEngine(unittest.TestCase):
    def setUp(self):
        self.mock_generator = MagicMock()
        self.mock_bus = MagicMock()
        self.engine = GoalDiscoveryEngine(
            goal_generator=self.mock_generator,
            event_bus=self.mock_bus,
            check_interval_seconds=900 # 15 mins
        )
        
    def test_discovery_interval(self):
        """Test that discovery respects interval."""
        # Setup mock goals
        self.mock_generator.generate_goals.return_value = []
        
        # 1. First run - should execute
        self.engine.run_discovery_cycle("building_1")
        self.mock_generator.generate_goals.assert_called_once()
        self.mock_generator.generate_goals.reset_mock()
        
        # 2. Immediate second run - should execution (interval not passed)
        self.engine.run_discovery_cycle("building_1")
        self.mock_generator.generate_goals.assert_not_called()
        
        # 3. Time travel -> force run
        self.engine.last_run = (datetime.now() - timedelta(minutes=20)).timestamp()
        
        self.engine.run_discovery_cycle("building_1")
        self.mock_generator.generate_goals.assert_called_once()

    def test_goal_deduplication(self):
        """Test that we don't spam duplicate goals."""
        goal1 = ProactiveGoal(
            goal_id="g1", title="Fix Chiller", 
            goal_type="risk_mitigation", priority="high", 
            score=0.9, description="desc", 
            source_engine="pred", building_id="b1",
            potential_savings_qar=0, risk_reduction="high",
            recommended_deadline=datetime(2025,1,1), suggested_actions=[],
            equipment_ids=["CH-01"]
        )
        
        self.mock_generator.generate_goals.return_value = [goal1]
        
        # 1. First find
        new_goals = self.engine.run_discovery_cycle("building_1")
        self.assertEqual(len(new_goals), 1)
        self.mock_bus.publish.assert_called_once()
        
        # 2. Second find (same goal, diff UUID but same sig)
        # Force interval bypass
        self.engine.last_run = 0 
        self.mock_bus.reset_mock()
        
        # Create identical goal (different object)
        goal1_dup = ProactiveGoal(
            goal_id="g2", title="Fix Chiller", 
            goal_type="risk_mitigation", priority="high", 
            score=0.9, description="desc", 
            source_engine="pred", building_id="b1",
            potential_savings_qar=0, risk_reduction="high",
            recommended_deadline=datetime(2025,1,1), suggested_actions=[],
            equipment_ids=["CH-01"]
        )
        self.mock_generator.generate_goals.return_value = [goal1_dup]
        
        new_goals = self.engine.run_discovery_cycle("building_1")
        self.assertEqual(len(new_goals), 0) # Should be deduped
        self.mock_bus.publish.assert_not_called()

if __name__ == "__main__":
    unittest.main()
