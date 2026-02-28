
import unittest
import time
import json
import os
from unittest.mock import MagicMock
from dotenv import load_dotenv

# Load environment variables for real API keys
load_dotenv()

from agent_home.learning.learning_engine import LearningEngine
from agent_home.llm_agent.llm_agent import LLMAgent
from arvis_core.event_bus.event_bus import EventBus
from agent_home.state_engine.state_engine import StateEngine

class TestTitansLive(unittest.TestCase):
    """
    LIVE API TEST for Titans Loop.
    Requires GROQ_API_KEY (or other provider key) to be set in .env
    """
    
    def setUp(self):
        # 1. Check for API Key
        if not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
             self.skipTest("No API keys found in environment. Skipping live test.")

        # 2. Setup Real Infrastructure
        self.event_bus = EventBus()
        self.state_engine = StateEngine(self.event_bus)
        
        # Mocks for side-effects
        self.automation_engine = MagicMock()
        self.tool_executor = MagicMock()
        
        # Real LLM Agent
        print("\n\n🤖 Initializing Real LLMAgent...")
        self.llm_agent = LLMAgent(
            self.event_bus, 
            self.state_engine, 
            self.automation_engine
        )
        
        # Real Learning Engine
        self.learning_engine = LearningEngine(
            self.event_bus,
            self.state_engine,
            self.automation_engine,
            self.tool_executor,
            interval_minutes=60,
            history_limit=100,
            llm_client=self.llm_agent
        )

    def test_live_pattern_detection(self):
        """
        Injects a clear, artificial pattern into history and asserts
        that the REAL Cloud LLM detects it and calls create_routine.
        """
        print(f"📡 Using Provider: {self.llm_agent.provider}")
        
        # 1. Synthesize History: "Bedroom Light turned on at 10:00 PM" for 7 days
        # This is a VERY strong pattern.
        print("📝 Synthesizing 7 days of 'Bedroom Light ON at 10 PM'...")
        history = []
        base_time = time.time()
        
        # Align to 10:00 PM local time roughly
        # Just use offsets to ensure consistency relative to each other
        for day in range(7):
            # 1 day = 86400 seconds
            # Jitter by +/- 2 minutes to make it realistic
            import random
            jitter = random.randint(-120, 120)
            
            ts = base_time - (day * 86400) + jitter
            
            history.append({
                "type": "relay_toggled",
                "timestamp": ts,
                "payload": {"device": "bedroom_light", "state": "on"}
            })
            
        # Add some noise
        for _ in range(5):
             history.append({
                "type": "relay_toggled",
                "timestamp": base_time - random.randint(0, 7*86400),
                "payload": {"device": "random_fan", "state": "off"}
            })
            
        self.state_engine.get_history = MagicMock(return_value=history)
        self.automation_engine.list.return_value = [] 
        
        # 2. Run Learning Cycle
        print("🧠 Running Learning Cycle (calling Cloud LLM)...")
        self.learning_engine.run_learning_cycle()
        
        # 3. Verify Results
        # Check if ToolExecutor was called
        if not self.tool_executor.execute.called:
            print("❌ No tool calls generated. The LLM missed the pattern.")
            
            # Print logic to see why
            # (In a real debug session we'd check logs, here we rely on stdout)
            self.fail("LLM did not generate any tool calls for a strong 7-day pattern.")
        
        calls = self.tool_executor.execute.call_args[0][0]
        print(f"✅ Generated {len(calls)} tool calls.")
        
        # Analyze first call
        first_call = calls[0]
        print(f"🔧 Tool: {first_call['tool']}")
        print(f"📝 Args: {json.dumps(first_call['args'], indent=2)}")
        
        # Assertion: Should be create_routine or ask_user
        self.assertIn(first_call['tool'], ["create_routine", "ask_user"])
        
        if first_call['tool'] == "create_routine":
            args = first_call['args']
            # Name might vary, but should contain "Bedroom"
            self.assertTrue("Bedroom" in args.get("name", "") or "bedroom" in args.get("name", "").lower(), 
                            "Routine name should relate to Bedroom")
            
            # Action should be turning on bedroom light
            actions = args.get("actions", [])
            self.assertTrue(len(actions) > 0)
            self.assertEqual(actions[0]["tool"], "turn_on")
            self.assertIn("bedroom", actions[0]["args"].get("device_id", "").lower())

if __name__ == '__main__':
    unittest.main()
