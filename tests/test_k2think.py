"""
K2 Think LLM Provider Test Suite
================================
Tests the K2 Think reasoning model's capabilities including:
- Response parsing (<think>/<answer> tags)
- API connectivity
- Tool calling
- Reasoning quality

Requires K2THINK_API_KEY in .env
"""

import unittest
import os
import re
import json
import time
from unittest.mock import MagicMock, patch
from dotenv import load_dotenv

load_dotenv()


class TestK2ThinkResponseParsing(unittest.TestCase):
    """Unit tests for K2 Think response parsing (no API calls)."""
    
    def setUp(self):
        """Import the LLMAgent class."""
        from agent.llm_agent.llm_agent import LLMAgent
        
        # Create a minimal mock agent to test parsing
        with patch.object(LLMAgent, '__init__', lambda x, *args, **kwargs: None):
            self.agent = LLMAgent(None, None, None)
            self.agent.provider = "k2think"
            # Import the parsing method
            from agent.llm_agent.llm_agent import LLMAgent as RealAgent
            self.agent._parse_k2think_response = RealAgent._parse_k2think_response.__get__(self.agent)
    
    def test_parse_simple_answer(self):
        """Test parsing response with both think and answer tags."""
        response = "<think>Let me analyze this request...</think><answer>Turn on the lights.</answer>"
        answer, thinking = self.agent._parse_k2think_response(response)
        
        self.assertEqual(answer, "Turn on the lights.")
        self.assertEqual(thinking, "Let me analyze this request...")
    
    def test_parse_multiline_response(self):
        """Test parsing multiline think/answer content."""
        response = """<think>
Step 1: Analyze the user's request
Step 2: Determine the appropriate action
Step 3: Formulate response
</think>
<answer>
Based on your request, I'll turn on the living room lights.
The brightness is set to 75%.
</answer>"""
        
        answer, thinking = self.agent._parse_k2think_response(response)
        
        self.assertIn("turn on the living room lights", answer)
        self.assertIn("Step 1", thinking)
    
    def test_parse_answer_only(self):
        """Test parsing response with only answer tags."""
        response = "<answer>The temperature is 24°C.</answer>"
        answer, thinking = self.agent._parse_k2think_response(response)
        
        self.assertEqual(answer, "The temperature is 24°C.")
        self.assertEqual(thinking, "")
    
    def test_parse_no_tags(self):
        """Test parsing response without any tags (fallback behavior)."""
        response = "Just a plain text response."
        answer, thinking = self.agent._parse_k2think_response(response)
        
        self.assertEqual(answer, "Just a plain text response.")
        self.assertEqual(thinking, "")
    
    def test_parse_complex_reasoning(self):
        """Test parsing complex multi-step reasoning."""
        response = """<think>
The user asked about the weather. Let me check:
1. Current temperature: 22°C
2. Humidity: 65%
3. Forecast: Partly cloudy

I should provide a concise summary.
</think><answer>It's currently 22°C with 65% humidity. Partly cloudy today.</answer>"""
        
        answer, thinking = self.agent._parse_k2think_response(response)
        
        self.assertIn("22°C", answer)
        self.assertIn("Current temperature", thinking)


class TestK2ThinkLiveAPI(unittest.TestCase):
    """
    LIVE API tests for K2 Think model.
    Requires K2THINK_API_KEY in environment.
    """
    
    @classmethod
    def setUpClass(cls):
        """Check for API key before running live tests."""
        if not os.environ.get("K2THINK_API_KEY"):
            raise unittest.SkipTest("K2THINK_API_KEY not set. Skipping live API tests.")
    
    def setUp(self):
        """Initialize real K2 Think agent."""
        from agent.event_bus.event_bus import EventBus
        from agent.state_engine.state_engine import StateEngine
        from agent.llm_agent.llm_agent import LLMAgent
        
        # Force K2 Think provider
        os.environ["LLM_PROVIDER"] = "k2think"
        
        self.event_bus = EventBus()
        self.state_engine = StateEngine(self.event_bus)
        self.automation_engine = MagicMock()
        self.automation_engine.list.return_value = []
        
        print("\n🤖 Initializing K2 Think LLMAgent...")
        self.llm_agent = LLMAgent(
            self.event_bus,
            self.state_engine,
            self.automation_engine,
            subscribe_to_voice=False
        )
        
        self.assertEqual(self.llm_agent.provider, "k2think", 
                        "Failed to initialize K2 Think provider")
        print(f"✅ Using model: {self.llm_agent.k2think_model}")
    
    def test_simple_chat_response(self):
        """Test basic chat functionality with K2 Think."""
        print("\n📡 Testing simple chat response...")
        
        # Capture published events
        responses = []
        self.event_bus.subscribe("agent_response", lambda e: responses.append(e))
        
        # Send a simple question
        event = {
            "type": "voice_command",
            "timestamp": time.time(),
            "payload": {"text": "What is 2 + 2?"}
        }
        
        self.llm_agent.handle(event)
        
        # Allow time for response
        time.sleep(2)
        
        # Check response
        self.assertTrue(len(responses) > 0, "No response received from K2 Think")
        response_text = responses[0].get("payload", {}).get("text", "")
        print(f"📝 Response: {response_text}")
        
        # Should contain "4" in the answer
        self.assertIn("4", response_text)
    
    def test_reasoning_capability(self):
        """Test K2 Think's reasoning on a logic problem."""
        print("\n🧠 Testing reasoning capability...")
        
        responses = []
        self.event_bus.subscribe("agent_response", lambda e: responses.append(e))
        
        # A problem requiring multi-step reasoning
        event = {
            "type": "voice_command",
            "timestamp": time.time(),
            "payload": {"text": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?"}
        }
        
        self.llm_agent.handle(event)
        time.sleep(5)  # Reasoning takes longer
        
        self.assertTrue(len(responses) > 0, "No response received")
        response_text = responses[0].get("payload", {}).get("text", "")
        print(f"📝 Response: {response_text}")
        
        # Correct answer is 5 minutes
        self.assertIn("5", response_text.lower())
    
    def test_tool_generation(self):
        """Test that K2 Think can generate tool calls."""
        print("\n🔧 Testing tool call generation...")
        
        from agent.llm_agent.tools_schema import TOOLS_SCHEMA
        
        system_prompt = """You are ARVIS, a smart home assistant. 
        When asked to control devices, use the appropriate tools."""
        
        user_content = "Turn on the bedroom light"
        
        tool_calls = self.llm_agent.generate_tool_calls(
            system_prompt=system_prompt,
            user_content=user_content,
            tools=TOOLS_SCHEMA
        )
        
        print(f"📝 Generated tool calls: {json.dumps(tool_calls, indent=2)}")
        
        # Should generate a turn_on tool call
        self.assertTrue(len(tool_calls) > 0, "No tool calls generated")
        self.assertEqual(tool_calls[0]["tool"], "turn_on")
        self.assertIn("bedroom", tool_calls[0]["args"].get("device_id", "").lower())
    
    def test_rate_limit_handling(self):
        """Test behavior under rate limiting (20 RPM)."""
        print("\n⏱️ Testing rate limit awareness...")
        
        # K2 Think has 20 RPM limit - just verify we don't crash on rapid calls
        responses = []
        self.event_bus.subscribe("agent_response", lambda e: responses.append(e))
        
        # Send 3 rapid requests
        for i in range(3):
            event = {
                "type": "voice_command",
                "timestamp": time.time(),
                "payload": {"text": f"Quick test {i+1}"}
            }
            self.llm_agent.handle(event)
            time.sleep(0.5)
        
        # Just verify no exceptions were raised
        print(f"✅ Completed {3} rapid requests without errors")


class TestK2ThinkProviderInit(unittest.TestCase):
    """Test K2 Think provider initialization."""
    
    def test_provider_selection_explicit(self):
        """Test explicit K2 Think provider selection."""
        if not os.environ.get("K2THINK_API_KEY"):
            self.skipTest("K2THINK_API_KEY not set")
        
        from agent.event_bus.event_bus import EventBus
        from agent.state_engine.state_engine import StateEngine
        from agent.llm_agent.llm_agent import LLMAgent
        
        os.environ["LLM_PROVIDER"] = "k2think"
        
        event_bus = EventBus()
        state_engine = StateEngine(event_bus)
        automation_engine = MagicMock()
        
        agent = LLMAgent(event_bus, state_engine, automation_engine, subscribe_to_voice=False)
        
        self.assertEqual(agent.provider, "k2think")
        self.assertEqual(agent.k2think_model, "MBZUAI-IFM/K2-Think")
    
    def test_provider_selection_alias(self):
        """Test K2 Think provider selection via 'k2' alias."""
        if not os.environ.get("K2THINK_API_KEY"):
            self.skipTest("K2THINK_API_KEY not set")
        
        from agent.event_bus.event_bus import EventBus
        from agent.state_engine.state_engine import StateEngine
        from agent.llm_agent.llm_agent import LLMAgent
        
        os.environ["LLM_PROVIDER"] = "k2"
        
        event_bus = EventBus()
        state_engine = StateEngine(event_bus)
        automation_engine = MagicMock()
        
        agent = LLMAgent(event_bus, state_engine, automation_engine, subscribe_to_voice=False)
        
        self.assertEqual(agent.provider, "k2think")


if __name__ == '__main__':
    print("=" * 60)
    print("K2 Think LLM Provider Test Suite")
    print("=" * 60)
    
    # Run with verbosity
    unittest.main(verbosity=2)
