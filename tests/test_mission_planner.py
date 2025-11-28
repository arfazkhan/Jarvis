import unittest
from agent_mission.mission_planner import MissionPlanner
from agent_mission.base.mission_step import StepType

class TestMissionPlanner(unittest.TestCase):
    
    def setUp(self):
        self.planner = MissionPlanner(template_dir="agent_mission/templates")
    
    def test_template_loading(self):
        print("\n[Test] Mission Planner Template Loading")
        
        # Verify templates loaded
        self.assertIn("sleep_optimization", self.planner.templates)
        self.assertIn("energy_saver", self.planner.templates)
        print("✅ Templates loaded in MissionPlanner")
    
    def test_generate_sleep_plan(self):
        print("\n[Test] Generate Sleep Optimization Plan")
        
        context = {"user_id": "test_user"}
        plan = self.planner.generate_plan("sleep_optimization", context)
        
        # Verify plan structure
        self.assertIsNotNone(plan)
        
        # Check nodes exist
        nodes = plan.nodes
        self.assertGreater(len(nodes), 0)
        
        # Check specific steps from template
        self.assertIn("collect_sleep_data", nodes)
        self.assertIn("create_bedtime_scene", nodes)
        
        print(f"✅ Sleep plan generated with {len(nodes)} steps")
    
    def test_generate_energy_plan(self):
        print("\n[Test] Generate Energy Saver Plan")
        
        context = {"user_id": "test_user"}
        plan = self.planner.generate_plan("energy_saver", context)
        
        nodes = plan.nodes
        self.assertGreater(len(nodes), 0)
        self.assertIn("detect_idle_devices", nodes)
        print(f"✅ Energy plan generated with {len(nodes)} steps")
    
    def test_plan_has_valid_dag(self):
        print("\n[Test] Plan is Valid DAG (No Cycles)")
        
        context = {"user_id": "test_user"}
        plan = self.planner.generate_plan("sleep_optimization", context)
        
        # get_execution_layers will fail if there are cycles
        layers = plan.get_execution_layers()
        
        self.assertGreater(len(layers), 0)
        print(f"✅ Valid DAG with {len(layers)} execution layers")
    
    def test_step_types_mapped_correctly(self):
        print("\n[Test] Step Types Mapped Correctly")
        
        context = {"user_id": "test_user"}
        plan = self.planner.generate_plan("sleep_optimization", context)
        
        # Check a specific node
        collect_step = plan.nodes.get("collect_sleep_data")
        self.assertIsNotNone(collect_step)
        # PlanNode stores action as string
        self.assertEqual(collect_step.action, StepType.COLLECTION.value)
        
        scene_step = plan.nodes.get("create_bedtime_scene")
        self.assertIsNotNone(scene_step)
        self.assertEqual(scene_step.action, StepType.SCENE.value)
        
        print("✅ Step types mapped correctly from YAML")
    
    def test_rebuild_plan(self):
        print("\n[Test] Rebuild Plan with Metrics")
        
        context = {"user_id": "test_user"}
        old_plan = self.planner.generate_plan("sleep_optimization", context)
        
        metrics = {"bedtime_variance": 50}
        new_plan = self.planner.rebuild_plan(old_plan, metrics, "sleep_optimization", context)
        
        # For MVP, rebuild just regenerates
        self.assertIsNotNone(new_plan)
        print("✅ Plan rebuild successful")

if __name__ == "__main__":
    unittest.main()
