
import unittest
import time
import json
from unittest.mock import MagicMock, patch
from agent.learning.learning_engine import LearningEngine
from agent.llm_agent.prompt import TOOLS_SCHEMA

class TestTitansProactive(unittest.TestCase):
    def setUp(self):
        self.event_bus = MagicMock()
        self.state_engine = MagicMock()
        self.automation_engine = MagicMock()
        self.tool_executor = MagicMock()
        
        # Mock LLMAgent
        self.mock_llm = MagicMock()
        # Mock generate_tool_calls to return a specific routine creation
        self.mock_llm.generate_tool_calls.return_value = [{
            "tool": "create_routine",
            "args": {
                "name": "Morning Coffee",
                "trigger": {"type": "time", "time": "08:00"},
                "actions": [{"tool": "turn_on", "args": {"device_id": "coffee_machine", "endpoint": 1}}]
            }
        }]
        
        self.engine = LearningEngine(
            self.event_bus,
            self.state_engine,
            self.automation_engine,
            self.tool_executor,
            interval_minutes=60,
            history_limit=50,
            llm_client=self.mock_llm
        )

    def test_proactive_routine_creation(self):
        """Test that the engine identifies a pattern and creates a routine"""
        print("\n[Test] simulating 5 days of history...")
        
        # Simulate 5 days of "turn on coffee" at 8:00 AM
        history = []
        for day in range(5):
            ts = time.time() - (day * 86400)
            history.append({
                "type": "relay_toggled",
                "timestamp": ts,
                "payload": {"device": "coffee_machine", "state": "on"}
            })
            
        self.state_engine.get_history.return_value = history
        self.automation_engine.list.return_value = [] # No existing routines
        
        # Run learning cycle
        self.engine.run_learning_cycle()
        
        # Verify LLM was asked
        self.mock_llm.generate_tool_calls.assert_called_once()
        call_args = self.mock_llm.generate_tool_calls.call_args
        self.assertIn("recent_history", call_args.kwargs["user_content"])
        
        # Verify ToolExecutor was called with the suggested routine
        self.tool_executor.execute.assert_called_once()
        executed_calls = self.tool_executor.execute.call_args[0][0]
        self.assertEqual(len(executed_calls), 1)
        self.assertEqual(executed_calls[0]["tool"], "create_routine")
        self.assertEqual(executed_calls[0]["args"]["name"], "Morning Coffee")
        
        print("✅ Titans loop successfully analyzed history and proposed a routine!")

if __name__ == '__main__':
    unittest.main()
