import unittest
import tempfile
import shutil
from agent_mission.user_pattern_store import UserPatternStore, UserPatterns

class TestUserPatternStore(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = UserPatternStore(storage_path=self.temp_dir)
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_save_and_load_patterns(self):
        print("\n[Test] Save & Load User Patterns")
        
        patterns = UserPatterns(
            user_id="test_user",
            bedtime_variance_minutes=35.0,
            irregular_sleep_count=2,
            work_pattern_consistency=0.75
        )
        
        self.store.save_patterns(patterns)
        loaded = self.store.load_patterns("test_user")
        
        self.assertEqual(loaded.user_id, "test_user")
        self.assertEqual(loaded.bedtime_variance_minutes, 35.0)
        self.assertEqual(loaded.work_pattern_consistency, 0.75)
        print("✅ Patterns saved and loaded correctly")
    
    def test_update_sleep_patterns(self):
        print("\n[Test] Update Sleep Patterns")
        
        bedtimes = [82800, 83100, 82500]  # ~23:00
        waketimes = [25200, 25500]  # ~07:00
        
        self.store.update_sleep_patterns("test_user", bedtimes, waketimes)
        patterns = self.store.load_patterns("test_user")
        
        self.assertGreater(patterns.avg_bedtime_seconds, 0)
        self.assertGreater(patterns.bedtime_variance_minutes, 0)
        print(f"✅ Sleep patterns updated (variance: {patterns.bedtime_variance_minutes:.1f} min)")
    
    def test_update_energy_patterns(self):
        print("\n[Test] Update Energy Patterns")
        
        self.store.update_energy_patterns("test_user", away_hours=3.5, idle_count=5)
        patterns = self.store.load_patterns("test_user")
        
        self.assertEqual(patterns.away_duration_hours, 3.5)
        self.assertEqual(patterns.idle_device_count, 5)
        print("✅ Energy patterns updated")
    
    def test_update_work_patterns(self):
        print("\n[Test] Update Work Patterns")
        
        self.store.update_work_patterns("test_user", consistency=0.85, start_hour=9, duration_hours=8.0)
        patterns = self.store.load_patterns("test_user")
        
        self.assertEqual(patterns.work_pattern_consistency, 0.85)
        self.assertEqual(patterns.avg_work_start_hour, 9)
        print("✅ Work patterns updated")
    
    def test_get_patterns_as_dict(self):
        print("\n[Test] Get Patterns as Dict")
        
        self.store.update_sleep_patterns("test_user", [82800], [25200])
        patterns_dict = self.store.get_patterns_as_dict("test_user")
        
        self.assertIn("bedtime_variance_minutes", patterns_dict)
        self.assertIn("user_id", patterns_dict)
        print("✅ Patterns dict conversion works")

if __name__ == "__main__":
    unittest.main()
