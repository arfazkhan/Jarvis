import unittest
from unittest.mock import MagicMock, patch
import sys
import json

# Mock Groq
mock_groq = MagicMock()
sys.modules["groq"] = mock_groq

from agent_cognitive.context_graph import ContextGraph
from agent_plan.scene_engine.scene_resolver import SceneResolver
from agent_plan.plan_generator import PlanGenerator

class TestPhase3Planning(unittest.TestCase):
    def setUp(self):
        self.context = MagicMock(spec=ContextGraph)
        self.resolver = SceneResolver(self.context)

    def test_scene_resolution(self):
        """Verify scene resolution and target expansion"""
        print("\n[Test] Scene Resolution")
        
        # Mock ContextGraph to return lights
        self.context.get_nodes_by_type.return_value = [
            {"id": "light_1", "type": "light"},
            {"id": "light_2", "type": "light"}
        ]
        
        actions = self.resolver.resolve_scene("cozy_mode")
        
        # Verify actions generated
        self.assertTrue(len(actions) > 0)
        
        # Check for light expansion
        light_actions = [a for a in actions if a["params"].get("device") in ["light_1", "light_2"]]
        self.assertTrue(len(light_actions) >= 2)
        
        print(f"✅ Resolved 'cozy_mode' into {len(actions)} actions (Lights expanded)")

    def test_plan_generator(self):
        """Verify PlanGenerator parses LLM JSON"""
        print("\n[Test] Plan Generator")
        
        # Mock Groq response
        mock_client = MagicMock()
        mock_groq.Groq.return_value = mock_client
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = json.dumps({
            "plan": [
                {"action": "turn_on", "params": {"device": "tv"}},
                {"action": "dim", "params": {"device": "light_1"}}
            ]
        })
        mock_client.chat.completions.create.return_value = mock_completion
        
        with patch.dict("os.environ", {"GROQ_API_KEY": "fake"}):
            generator = PlanGenerator()
            plan = generator.generate_plan("Watch TV")
            
            self.assertEqual(len(plan), 2)
            self.assertEqual(plan[0]["action"], "turn_on")
            self.assertEqual(plan[0]["params"]["device"], "tv")
            print("✅ PlanGenerator parsed JSON plan correctly")

if __name__ == "__main__":
    unittest.main()
