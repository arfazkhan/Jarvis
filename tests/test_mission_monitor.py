import unittest
from agent.event_bus.event_bus import EventBus
from agent_mission.mission_store import MissionStore
from agent_mission.mission_monitor import MissionMonitor
from agent_mission.base.mission import Mission, MissionStatus
import tempfile
import shutil

class TestMissionMonitor(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.store = MissionStore(storage_path=self.temp_dir)
        self.monitor = MissionMonitor(self.event_bus, self.store)
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_monitor_initialization(self):
        print("\n[Test] Mission Monitor Initialization")
        
        # Trigger mission_started event
        self.event_bus.publish({
            "type": "mission_started",
            "source": "test",
            "payload": {
                "mission_id": "test_mission_001",
                "mission_type": "sleep_optimization",
                "user_id": "test_user"
            }
        })
        
        # Check metrics initialized
        self.assertIn("test_mission_001", self.monitor.mission_metrics)
        print("✅ Monitor initialized metrics on mission start")
    
    def test_evaluate_sleep_mission(self):
        print("\n[Test] Evaluate Sleep Mission")
        
        # Create and save mission
        mission = Mission(
            mission_id="sleep_001",
            mission_type="sleep_optimization",
            status=MissionStatus.MONITORING
        )
        self.store.save_mission(mission)
        
        # Initialize metrics
        self.event_bus.publish({
            "type": "mission_started",
            "source": "test",
            "payload": {"mission_id": "sleep_001"}
        })
        
        # Evaluate with good data
        sensor_data = {
            "bedtimes": [82800, 83100, 82500],  # ~23:00 with low variance
            "wake_times": [25200, 25500, 25800],  # ~07:00
            "night_motion_count": 3
        }
        
        evaluation = self.monitor.evaluate_mission("sleep_001", sensor_data)
        
        self.assertIn("metrics", evaluation)
        self.assertIn("bedtime_variance", evaluation["metrics"])
        self.assertIn("score", evaluation)
        self.assertGreater(evaluation["score"], 0.5)  # Good metrics
        print(f"✅ Sleep mission evaluated (score: {evaluation['score']:.2f})")
    
    def test_evaluate_energy_mission(self):
        print("\n[Test] Evaluate Energy Mission")
        
        mission = Mission(
            mission_id="energy_001",
            mission_type="energy_saver",
            status=MissionStatus.MONITORING
        )
        self.store.save_mission(mission)
        
        self.event_bus.publish({
            "type": "mission_started",
            "source": "test",
            "payload": {"mission_id": "energy_001"}
        })
        
        # Good energy savings
        sensor_data = {
            "device_off_time_hours": 18,
            "total_time_hours": 24
        }
        
        evaluation = self.monitor.evaluate_mission("energy_001", sensor_data)
        
        self.assertEqual(evaluation["metrics"]["device_off_ratio"], 0.75)
        self.assertFalse(evaluation["needs_adaptation"])  # Good performance
        print("✅ Energy mission evaluated successfully")
    
    def test_needs_adaptation_trigger(self):
        print("\n[Test] Needs Adaptation Trigger")
        
        mission = Mission(
            mission_id="sleep_002",
            mission_type="sleep_optimization",
            status=MissionStatus.MONITORING
        )
        self.store.save_mission(mission)
        
        self.event_bus.publish({
            "type": "mission_started",
            "source": "test",
            "payload": {"mission_id": "sleep_002"}
        })
        
        # Bad metrics (high variance)
        sensor_data = {
            "bedtimes": [82800, 90000, 75000],  # High variance
            "wake_times": [25200, 25500],
            "night_motion_count": 15  # Too many motion events
        }
        
        evaluation = self.monitor.evaluate_mission("sleep_002", sensor_data)
        
        self.assertTrue(evaluation["needs_adaptation"])
        self.assertGreater(len(evaluation["recommendations"]), 0)
        print(f"✅ Adaptation triggered with {len(evaluation['recommendations'])} recommendations")
    
    def test_check_completion(self):
        print("\n[Test] Check Mission Completion")
        
        import time
        
        # Create old mission (simulating 4 days ago)
        mission = Mission(
            mission_id="sleep_003",
            mission_type="sleep_optimization",
            status=MissionStatus.MONITORING,
            start_ts=time.time() - (4 * 24 * 3600)  # 4 days ago
        )
        mission.metrics = {
            "bedtime_variance": 25,  # Good
            "wake_time_stability": 0.85  # Good
        }
        self.store.save_mission(mission)
        
        should_complete = self.monitor.check_completion("sleep_003")
        
        self.assertTrue(should_complete)
        print("✅ Mission completion detected correctly")
    
    def test_completion_not_too_early(self):
        print("\n[Test] Completion Not Triggered Too Early")
        
        import time
        
        # Recent mission (1 day old)
        mission = Mission(
            mission_id="sleep_004",
            mission_type="sleep_optimization",
            status=MissionStatus.MONITORING,
            start_ts=time.time() - (1 * 24 * 3600)  # 1 day ago
        )
        mission.metrics = {
            "bedtime_variance": 25,
            "wake_time_stability": 0.85
        }
        self.store.save_mission(mission)
        
        should_complete = self.monitor.check_completion("sleep_004")
        
        self.assertFalse(should_complete)  # Too early
        print("✅ Early completion prevented correctly")

if __name__ == "__main__":
    unittest.main()
