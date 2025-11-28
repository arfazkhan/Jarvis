import unittest
import tempfile
import shutil
from pathlib import Path
from agent.event_bus.event_bus import EventBus
from agent_mission.mission_manager import MissionManager
from agent_mission.mission_store import MissionStore
from agent_mission.base.mission import Mission, MissionStatus
from agent_mission.base.mission_context import MissionContext

class TestMissionManager(unittest.TestCase):
    
    def setUp(self):
        # Create temp directory for test storage
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.manager = MissionManager(self.event_bus, template_dir="agent_mission/templates")
        # Override store to use temp directory
        self.manager.store = MissionStore(storage_path=self.temp_dir)
        
    def tearDown(self):
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)
    
    def test_load_mission_templates(self):
        print("\n[Test] Mission Template Loading")
        # Verify all 4 templates loaded
        self.assertIn("sleep_optimization", self.manager.templates)
        self.assertIn("energy_saver", self.manager.templates)
        self.assertIn("home_security", self.manager.templates)
        self.assertIn("focus_productivity", self.manager.templates)
        
        # Verify template structure
        sleep_template = self.manager.templates["sleep_optimization"]
        self.assertIn("goals", sleep_template)
        self.assertIn("plan_template", sleep_template)
        self.assertIn("metrics", sleep_template)
        print("✅ All 4 mission templates loaded correctly")
    
    def test_start_mission(self):
        print("\n[Test] Start Mission")
        context = MissionContext(user_id="test_user")
        
        # Start sleep optimization mission
        mission = self.manager.start_mission("sleep_optimization", context)
        
        self.assertEqual(mission.mission_type, "sleep_optimization")
        self.assertEqual(mission.status, MissionStatus.INIT)
        self.assertEqual(mission.user_id, "test_user")
        self.assertIsNotNone(mission.mission_id)
        print(f"✅ Mission started: {mission.mission_id}")
        
    def test_prevent_duplicate_missions(self):
        print("\n[Test] Prevent Duplicate Active Missions")
        context = MissionContext(user_id="test_user")
        
        # Start first mission
        mission1 = self.manager.start_mission("sleep_optimization", context)
        
        # Try to start another - should fail
        with self.assertRaises(ValueError) as cm:
            self.manager.start_mission("sleep_optimization", context)
        
        self.assertIn("already active", str(cm.exception))
        print("✅ Duplicate mission prevention works")
    
    def test_stop_mission(self):
        print("\n[Test] Stop Mission")
        context = MissionContext(user_id="test_user")
        mission = self.manager.start_mission("energy_saver", context)
        
        # Stop mission
        self.manager.stop_mission(mission.mission_id)
        
        # Verify status changed
        status = self.manager.get_status(mission.mission_id)
        self.assertEqual(status["status"], MissionStatus.COMPLETED.value)
        print("✅ Mission stopped successfully")
    
    def test_get_status(self):
        print("\n[Test] Get Mission Status")
        context = MissionContext(user_id="test_user")
        mission = self.manager.start_mission("home_security", context)
        
        status = self.manager.get_status(mission.mission_id)
        
        self.assertEqual(status["mission_id"], mission.mission_id)
        self.assertEqual(status["type"], "home_security")
        self.assertEqual(status["status"], MissionStatus.INIT.value)
        print("✅ Mission status retrieved correctly")
    
    def test_list_active_missions(self):
        print("\n[Test] List Active Missions")
        context = MissionContext(user_id="test_user")
        
        # Start multiple missions
        m1 = self.manager.start_mission("sleep_optimization", context)
        m2 = self.manager.start_mission("energy_saver", context)
        
        active = self.manager.list_active_missions()
        
        self.assertEqual(len(active), 2)
        self.assertIn(m1.mission_id, active)
        self.assertIn(m2.mission_id, active)
        print(f"✅ Listed {len(active)} active missions")
    
    def test_update_mission_status(self):
        print("\n[Test] Update Mission Status")
        context = MissionContext(user_id="test_user")
        mission = self.manager.start_mission("focus_productivity", context)
        
        # Update to PLANNING
        self.manager.update_mission_status(mission.mission_id, MissionStatus.PLANNING)
        
        status = self.manager.get_status(mission.mission_id)
        self.assertEqual(status["status"], MissionStatus.PLANNING.value)
        print("✅ Mission status updated: INIT → PLANNING")

if __name__ == "__main__":
    unittest.main()
