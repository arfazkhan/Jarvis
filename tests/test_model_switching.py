import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import os
import sys

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_commercial.bms_llm_agent import BMSLLMAgent, DEFAULT_ENGLISH_MODEL, DEFAULT_ARABIC_MODEL
from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

class TestModelSwitching(unittest.TestCase):
    
    def setUp(self):
        # Allow real env vars to pass through
        # If keys are missing, we skip
        self.k2_key = os.getenv("K2THINK_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        
        if not self.k2_key or not self.groq_key:
            print("⚠️ Skipping integration test: Missing API keys")
            self.skipTest("Missing K2THINK_API_KEY or GROQ_API_KEY")

    def tearDown(self):
        pass

    def test_detect_language(self):
        """Verify Arabic detection logic."""
        agent = BMSLLMAgent()
        self.assertEqual(agent._detect_language("Hello World"), "en")
        self.assertEqual(agent._detect_language("مرحبا بالعالم"), "ar")
        self.assertEqual(agent._detect_language("Temperature is 24 درجة مئوية"), "ar") 

    # We SPY on the method using wraps to keep original behavior
    @patch("agent_unified.llm.UnifiedLLM._ask_provider", side_effect=UnifiedLLM._ask_provider, autospec=True)
    def test_chat_switches_model(self, mock_ask_provider):
        """Verify model parameter changes using REAL UnifiedLLM (Integration Test)."""
        
        agent = BMSLLMAgent()
        
        # Test 1: English
        print("\nTesting English Query (Real Network Call)...")
        loop = asyncio.get_event_loop()
        # Using a simple query to save tokens/time
        response = loop.run_until_complete(agent.chat("Hi"))
        print(f"DEBUG Response: {response.text}")
        
        # Verify call args of the SPY
        # args: (agent, system_prompt, messages, tools, tool_choice, override_model)
        # We want to check override_model (index 5)
        
        # Filter calls to find the one from chat()
        # There might be tool calls too.
        # Chat call is usually the last one or the one without tools if simple.
        
        # Check call_args_list
        # We expect at least one call to _ask_provider
        self.assertTrue(mock_ask_provider.called)
        
        # Find the call with override_model argument
        calls = mock_ask_provider.call_args_list
        
        # For English, verify at least one call had override_model=None
        en_call_found = False
        for call in calls:
             args, kwargs = call
             # override_model is 6th arg (index 5) or in kwargs
             override = kwargs.get('override_model')
             if override is None: 
                 # Also check arg position 5 if present
                 if len(args) > 5:
                     if args[5] is None: en_call_found = True
                 else:
                     en_call_found = True
        
        self.assertTrue(en_call_found, "Did not find English call with override_model=None")
        
        mock_ask_provider.reset_mock()
        
        # Test 2: Arabic
        print("\nTesting Arabic Query (Real Network Call)...")
        loop.run_until_complete(agent.chat("مرحبا"))
        
        # Verify overrides
        ar_call_found = False
        for call in mock_ask_provider.call_args_list:
             args, kwargs = call
             override = kwargs.get('override_model')
             if override == DEFAULT_ARABIC_MODEL:
                 ar_call_found = True
             elif len(args) > 5 and args[5] == DEFAULT_ARABIC_MODEL:
                 ar_call_found = True
                 
        self.assertTrue(ar_call_found, f"Did not find Arabic call with override_model={DEFAULT_ARABIC_MODEL}")
        
        print(f"✅ Verified Real Integration: English->Default, Arabic->{DEFAULT_ARABIC_MODEL}")


if __name__ == "__main__":
    unittest.main()
