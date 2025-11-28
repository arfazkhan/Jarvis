import unittest
from unittest.mock import MagicMock, patch
import sys
import json
import os

# Mock Groq removed for real LLM testing
# mock_groq = MagicMock()
# sys.modules["groq"] = mock_groq

from agent_cognitive.context_graph import ContextGraph
from agent_plan.scene_registry import SceneRegistry
from agent_plan.scene_engine import SceneEngine
from agent_plan.plan_generator import PlanGenerator

class TestPhase3PlanningRefactor(unittest.TestCase):
    def setUp(self):
        # Setup Registry with real config path
        self.registry = SceneRegistry(scenes_dir="config/scenes")
        
        # Setup Context Graph Mock
        self.context = MagicMock(spec=ContextGraph)
        self.context.get_nodes_by_type.return_value = [
            {"id": "light_living_room_1", "type": "lighting", "room": "living_room"},
            {"id": "ac_living_room", "type": "climate", "room": "living_room"}
        ]
        
        # Setup Engine
        self.engine = SceneEngine(self.context, self.registry)
        
        # Setup Generator
        # Requires GROQ_API_KEY
        self.generator = PlanGenerator(self.registry, self.engine)
        if not self.generator.client:
             print("WARNING: GROQ_API_KEY not found. LLM tests will fail.")

    def test_registry_load(self):
        """Verify SceneRegistry loads cozy_evening.json"""
        print("\n[Test] Registry Load")
        scene = self.registry.get_scene("cozy_evening")
        self.assertIsNotNone(scene)
        self.assertEqual(scene["name"], "Cozy Evening")
        print("✅ Registry loaded 'cozy_evening'")

    def test_scene_engine_resolution(self):
        """Verify SceneEngine resolves cozy_evening to steps"""
        print("\n[Test] Scene Engine Resolution")
        steps = self.engine.build_scene_plan("cozy_evening")
        
        # Should have steps for light and ac
        self.assertTrue(len(steps) >= 2)
        
        # Check light step
        light_steps = [s for s in steps if s["action"] == "set_light"]
        self.assertTrue(len(light_steps) > 0)
        self.assertEqual(light_steps[0]["params"]["brightness"], 0.3)
        
        print(f"✅ Resolved 'cozy_evening' into {len(steps)} steps")

    def test_plan_generator_rule_match(self):
        """Verify PlanGenerator uses rule matching for known scenes"""
        print("\n[Test] Plan Generator (Rule Match)")
        
        # Request matching "Cozy Evening" name
        request = {"utterance": "Activate Cozy Evening", "context": {}}
        plan = self.generator.generate_plan(request)
        
        self.assertEqual(plan["type"], "scene")
        self.assertEqual(plan["scene_id"], "cozy_evening")
        self.assertEqual(plan["origin"], "rules")
        self.assertTrue(len(plan["steps"]) > 0)
        print("✅ Rule matched 'Cozy Evening'")

    def test_plan_generator_llm(self):
        """Verify PlanGenerator uses LLM for unknown requests"""
        print("\n[Test] Plan Generator (LLM)")
        
        # Real LLM Call
        # "Make it romantic" should map to "cozy_evening" or similar if available
        
        request = {"utterance": "Make it romantic", "context": {}}
        plan = self.generator.generate_plan(request)
        
        # Verify we got a valid plan
        self.assertNotIn("error", plan)
        self.assertIn(plan["type"], ["scene", "custom"])
        self.assertEqual(plan["origin"], "llm")
        
        if plan["type"] == "scene":
             print(f"✅ LLM mapped 'Romantic' to scene '{plan['scene_id']}'")
        else:
             print(f"✅ LLM generated custom plan with {len(plan['steps'])} steps")

if __name__ == "__main__":
    unittest.main()
