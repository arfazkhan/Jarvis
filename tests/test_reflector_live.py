
import unittest
import time
import json
import os
import random
from unittest.mock import MagicMock
from dotenv import load_dotenv

# Load environment variables for real API keys
load_dotenv()

from agent.learning.reflector import Reflector
from agent.llm_agent.llm_agent import LLMAgent
from agent.event_bus.event_bus import EventBus
from agent.state_engine.state_engine import StateEngine

class TestReflectorLive(unittest.TestCase):
    """
    LIVE API TEST for ACE Reflector.
    Requires GROQ_API_KEY (or other provider key).
    """
    
    def setUp(self):
        # 1. Check for API Key
        if not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
             self.skipTest("No API keys found. Skipping live test.")

        # 2. Setup Real Infrastructure
        self.event_bus = EventBus()
        self.state_engine = StateEngine(self.event_bus)
        self.automation_engine = MagicMock()
        
        # Real LLM Agent
        print("\n\n🤖 Initializing Real LLMAgent...")
        self.llm_agent = LLMAgent(
            self.event_bus, 
            self.state_engine, 
            self.automation_engine
        )
        
        # Real Reflector
        self.reflector = Reflector(self.llm_agent)

    def test_live_correction_learning(self):
        """
        Simulate 7 days where the Agent repeatedly makes a mistake (Plays Rock)
        and the User corrects it ("No, play Jazz").
        
        Expectation: Reflector should output a log_lesson call about Jazz preference.
        """
        print(f"📡 Using Provider: {self.llm_agent.provider}")
        
        # 1. Synthesize History: 7 Days of "Rock -> No, Jazz"
        print("📝 Synthesizing 7 days of User Corrections...")
        history = []
        base_time = time.time()
        
        for day in range(7):
            # timestamps: Interaction happened ~7 PM each day
            ts_start = base_time - ((7 - day) * 86400)
            
            # Interaction 1: User asks for music
            history.append({
                "role": "user", 
                "content": "Play some music",
                "timestamp": ts_start
            })
            
            # Interaction 2: Agent picks Rock (The Mistake)
            history.append({
                "role": "agent",
                "content": "Playing 'Hard Rock Best Hits' playlist.",
                "timestamp": ts_start + 5
            })
            
            # Interaction 3: User corrects (The Lesson)
            history.append({
                "role": "user", 
                "content": "Ugh, no. I hate rock music. Stop it and play Jazz.",
                "timestamp": ts_start + 15
            })
            
            # Interaction 4: Agent complies
            history.append({
                "role": "agent",
                "content": "Stopping Rock. Playing 'Smooth Jazz' playlist.",
                "timestamp": ts_start + 20
            })
            
        print(f"    Generated {len(history)} interaction events.")
        
        # 2. Run Reflection
        print("🧠 Running Reflector (calling Cloud LLM)...")
        tool_calls = self.reflector.reflect(history)
        
        # 3. Verify Results
        if not tool_calls:
            self.fail("❌ Reflector returned NO tool calls. It failed to learn the lesson.")
            
        print(f"✅ Generated {len(tool_calls)} tool calls.")
        first_call = tool_calls[0]
        
        print(f"🔧 Tool: {first_call['tool']}")
        print(f"📝 Args: {json.dumps(first_call['args'], indent=2)}")
        
        self.assertEqual(first_call['tool'], "log_lesson")
        
        lesson_text = first_call['args'].get("lesson", "").lower()
        context_text = first_call['args'].get("context", "").lower()
        
        # Check if it learned the specific preference
        has_jazz = "jazz" in lesson_text
        has_rock = "rock" in lesson_text
        
        self.assertTrue(has_jazz or has_rock, 
                        f"Lesson should mention 'Jazz' or dislike of 'Rock'. Got: {lesson_text}")
        
        print("🎉 SUCCESS! The Agent learned your music preference from corrections.")

if __name__ == '__main__':
    unittest.main()
