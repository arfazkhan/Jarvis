import unittest
import time
from unittest.mock import MagicMock
from arvis_core.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.sensor_ingestion import SensorIngestion
from agent_sensors.state_estimator import StateEstimator
from agent_sensors.virtual_sensors.occupancy_sensor import OccupancySensor
from agent_sensors.virtual_sensors.presence_sensor import PresenceSensor

class TestPhase4Advanced(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.registry = SensorRegistry("agent_sensors/config/sensors.yaml")
        self.ingestion = SensorIngestion(self.event_bus, self.registry)
        self.estimator = StateEstimator(self.event_bus, self.registry)
        
    # ----------------------------------------------------------------
    # 1. False Positives / False Negatives
    # ----------------------------------------------------------------
    def test_wifi_flapping_behavior(self):
        """Test WiFi disconnect grace period"""
        print("\n[Test] WiFi Flapping")
        ts = 1000.0
        
        # 1. Connect
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": True, "ts": ts})
        
        # 2. Disconnect (Flap)
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": False, "ts": ts + 10})
        
        # 3. Check immediately (should still be home due to grace period)
        with unittest.mock.patch('time.time', return_value=ts + 15):
             self.estimator._update_situation()
        
        situation = self.estimator.get_current_situation()
        self.assertEqual(situation.home_presence.state, "home")
        print("✅ WiFi Flapping handled (Grace Period)")
        
        # 4. Check after grace period (e.g., 70s later)
        with unittest.mock.patch('time.time', return_value=ts + 100):
             self.estimator._update_situation()
             
        situation = self.estimator.get_current_situation()
        # Should be unknown or away depending on other sensors (no motion -> unknown/away)
        # Without motion for 2h -> away. 100s -> < 30m -> home (low conf)
        self.assertEqual(situation.home_presence.state, "home") 
        self.assertLess(situation.home_presence.confidence, 0.5) 
        print("✅ WiFi Disconnect confirmed after grace period")

    def test_false_negative_quiet_user(self):
        """Test quiet user (reading) is still detected as occupied"""
        print("\n[Test] Quiet User")
        ts = 1000.0
        
        # 1. Enter Room (Motion)
        self.ingestion.ingest_event({"sensor_id": "motion_living_main", "value": True, "ts": ts})
        
        # 2. Turn on Light
        self.ingestion.ingest_event({"sensor_id": "light_living_main", "value": 100, "ts": ts + 10})
        
        # 3. Sit quietly for 8 minutes (Timeout is 5 mins)
        # But lights are ON.
        mock_now = ts + 480
        
        with unittest.mock.patch('time.time', return_value=mock_now):
             self.estimator._update_situation()
             
        situation = self.estimator.get_current_situation()
        occ = situation.room_occupancy["living_room"]
        
        self.assertTrue(occ.is_occupied)
        self.assertGreater(occ.confidence, 0.0)
        print("✅ Quiet user detected via lights")

    # ----------------------------------------------------------------
    # 2. Multi-person Confusion
    # ----------------------------------------------------------------
    def test_two_room_conflict(self):
        """Test Bedroom Sleeping vs Kitchen Cooking"""
        print("\n[Test] Two Room Conflict")
        ts = 1000.0
        
        # 1. Bedroom: Sleeping (No motion, dark, night)
        # Simulate motion long ago
        self.estimator.sleep_sensor.bedroom_last_motion = ts - 3600
        self.estimator.sleep_sensor.bedroom_lights_on = False
        
        # 2. Kitchen: Active (Motion)
        self.ingestion.ingest_event({"sensor_id": "motion_kitchen", "value": True, "ts": ts})
        
        # 3. Time = Night
        with unittest.mock.patch('time.time', return_value=ts):
            with unittest.mock.patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                self.estimator._update_situation()
                
        situation = self.estimator.get_current_situation()
        
        # Should prioritize active room (Snacking) over Sleep
        self.assertEqual(situation.activity_hint, "snacking")
        # Sleep state might still be "sleeping" internally for that sensor, but fusion overrides hint
        self.assertEqual(situation.sleep_state.state, "sleeping") 
        print("✅ Active room overrides sleep state in activity hint")

    # ----------------------------------------------------------------
    # 3. Temporal Edge Cases
    # ----------------------------------------------------------------
    def test_inactivity_long_window(self):
        """Test 12 hours inactivity -> Away"""
        print("\n[Test] Long Inactivity")
        ts = 1000.0
        
        # 1. Motion
        self.ingestion.ingest_event({"sensor_id": "motion_living_main", "value": True, "ts": ts})
        
        # 2. Advance 12 hours
        mock_now = ts + (12 * 3600)
        
        with unittest.mock.patch('agent_sensors.virtual_sensors.presence_sensor.time.time', return_value=mock_now):
             self.estimator._update_situation()
             
        situation = self.estimator.get_current_situation()
        self.assertEqual(situation.home_presence.state, "away")
        print("✅ Long inactivity detected as Away")

    # ----------------------------------------------------------------
    # 6. Stress Test
    # ----------------------------------------------------------------
    def test_stress_ingestion(self):
        """Ingest 1000 events"""
        print("\n[Test] Stress Ingestion")
        start = time.time()
        
        for i in range(1000):
            self.ingestion.ingest_event({
                "sensor_id": "motion_living_main",
                "value": True,
                "ts": start + i
            })
            
        duration = time.time() - start
        print(f"Ingested 1000 events in {duration:.4f}s")
        self.assertLess(duration, 1.0) # Should be very fast
        print("✅ Stress test passed")

if __name__ == "__main__":
    unittest.main()
