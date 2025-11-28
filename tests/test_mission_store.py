import unittest
import tempfile
import shutil
from pathlib import Path
from agent_mission.mission_store import MissionStore
from agent_mission.base.mission import Mission, MissionStatus

class TestMissionStore(unittest.TestCase):
    
    def setUp(self):
        # Create temp directory for test storage
        self.temp_dir = tempfile.mkdtemp()
        self.store = MissionStore(storage_path=self.temp_dir)
        
    def tearDown(self):
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)
    
    def test_save_and_load_mission(self):
        print("\n[Test] Save & Load Mission")
        
        # Create mission
        mission = Mission(
            mission_id="test_mission_001",
            mission_type="sleep_optimization",
            status=MissionStatus.INIT,
            user_id="test_user"
        )
        
        # Save
        self.store.save_mission(mission)
        
        # Load
        loaded = self.store.load_mission("test_mission_001")
        
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.mission_id, "test_mission_001")
        self.assertEqual(loaded.mission_type, "sleep_optimization")
        self.assertEqual(loaded.status, MissionStatus.INIT)
        print("✅ Mission saved and loaded correctly")
    
    def test_delete_mission(self):
        print("\n[Test] Delete Mission")
        
        mission = Mission(
            mission_id="test_mission_002",
            mission_type="energy_saver",
            status=MissionStatus.EXECUTING
        )
        
        self.store.save_mission(mission)
        self.store.delete_mission("test_mission_002")
        
        loaded = self.store.load_mission("test_mission_002")
        self.assertIsNone(loaded)
        print("✅ Mission deleted successfully")
    
    def test_list_missions_by_status(self):
        print("\n[Test] List Missions by Status")
        
        # Create missions with different statuses
        m1 = Mission(mission_id="m1", mission_type="sleep_optimization", status=MissionStatus.EXECUTING)
        m2 = Mission(mission_id="m2", mission_type="energy_saver", status=MissionStatus.EXECUTING)
        m3 = Mission(mission_id="m3", mission_type="home_security", status=MissionStatus.COMPLETED)
        
        self.store.save_mission(m1)
        self.store.save_mission(m2)
        self.store.save_mission(m3)
        
        # List executing missions
        executing = self.store.list_missions(status=MissionStatus.EXECUTING)
        self.assertEqual(len(executing), 2)
        
        # List completed missions
        completed = self.store.list_missions(status=MissionStatus.COMPLETED)
        self.assertEqual(len(completed), 1)
        print("✅ Mission filtering by status works")
    
    def test_get_active_missions(self):
        print("\n[Test] Get Active Missions")
        
        # Create mix of active and inactive missions
        m1 = Mission(mission_id="m1", mission_type="sleep_optimization", status=MissionStatus.PLANNING)
        m2 = Mission(mission_id="m2", mission_type="energy_saver", status=MissionStatus.MONITORING)
        m3 = Mission(mission_id="m3", mission_type="home_security", status=MissionStatus.COMPLETED)
        m4 = Mission(mission_id="m4", mission_type="focus_productivity", status=MissionStatus.ARCHIVED)
        
        for m in [m1, m2, m3, m4]:
            self.store.save_mission(m)
        
        active = self.store.get_active_missions()
        
        self.assertEqual(len(active), 2)  # Only m1 and m2
        active_ids = [m.mission_id for m in active]
        self.assertIn("m1", active_ids)
        self.assertIn("m2", active_ids)
        self.assertNotIn("m3", active_ids)
        self.assertNotIn("m4", active_ids)
        print(f"✅ Retrieved {len(active)} active missions (excluding COMPLETED/ARCHIVED)")
    
    def test_archive_mission(self):
        print("\n[Test] Archive Mission")
        
        mission = Mission(
            mission_id="m_archive",
            mission_type="sleep_optimization",
            status=MissionStatus.COMPLETED
        )
        
        self.store.save_mission(mission)
        self.store.archive_mission("m_archive")
        
        archived = self.store.load_mission("m_archive")
        self.assertEqual(archived.status, MissionStatus.ARCHIVED)
        print("✅ Mission archived successfully")

if __name__ == "__main__":
    unittest.main()
