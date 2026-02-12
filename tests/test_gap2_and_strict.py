"""
Verification test for Gap 2 (Outcome-Aware Scoring) and Gap 5 (Strict Model Roles).
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_unified.llm import UnifiedLLM
from agent_bms.graph import BMSGraph

class TestGapImplementation(unittest.TestCase):

    def setUp(self):
        # Patch environment variables to simulate configuration
        self.env_patcher = patch.dict(os.environ, {
            "K2THINK_API_KEY": "test-k2-key",
            "OPENAI_API_KEY": "test-openai-key",
            "GROQ_API_KEY": "test-groq-key"
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_strict_k2_role(self):
        """Verify that UnifiedLLM raises error if K2 fails, without fallback."""
        llm = UnifiedLLM()
        
        # Mock the _ask_provider method directly to simulate K2 failure
        # We need to target the method on the instance we created
        
        # But UnifiedLLM relies on global singletons _REASONING_AGENT
        # So we better patch the _ask_provider method
        
        with patch.object(llm, '_ask_provider', new_callable=AsyncMock) as mock_ask:
            # Simulate "LLM Error" response from K2
            mock_ask.return_value = MagicMock(content="LLM Error: Connection timed out")
            
            # Since we disabled fallback, this should raise RuntimeError
            # Instead of returning the error message or falling back
            loop = asyncio.get_event_loop()
            
            with self.assertRaises(RuntimeError) as context:
                loop.run_until_complete(llm.ask(messages=[{"role": "user", "content": "hi"}]))
            
            self.assertTrue("Connection timed out" in str(context.exception))
            print("✅ Verified Strict Mode: RuntimeError raised on K2 failure.")

    def test_outcome_aware_scoring(self):
        """Verify that graph paths are scored based on historical outcomes."""
        graph = BMSGraph()
        
        # Mock pattern store
        graph.pattern_store = MagicMock()
        
        # Case 1: High success rate (0.9)
        # Score should be 1.0 + (0.9 - 0.5) = 1.4
        graph.pattern_store.get_equipment_stats.return_value = {"success_rate": 0.9, "count": 10}
        score_high = graph.score_path(["chiller_1", "vav_101"])
        
        # Case 2: Low success rate (0.2)
        # Score should be 1.0 + (0.2 - 0.5) = 0.7
        graph.pattern_store.get_equipment_stats.return_value = {"success_rate": 0.2, "count": 10}
        score_low = graph.score_path(["chiller_1", "vav_101"])
        
        # Case 3: No history (0.5)
        # Score should be 1.0
        graph.pattern_store.get_equipment_stats.return_value = {"success_rate": 0.5, "count": 0}
        score_neutral = graph.score_path(["chiller_1", "vav_101"])
        
        self.assertGreater(score_high, score_neutral)
        self.assertLess(score_low, score_neutral)
        self.assertAlmostEqual(score_high, 1.4)
        
        print(f"✅ Verified Outcome Reranking: High={score_high}, Low={score_low}")

if __name__ == "__main__":
    unittest.main()
