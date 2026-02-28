import unittest
import time
from unittest.mock import MagicMock
from arvis_core.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.sensor_ingestion import SensorIngestion
from agent_sensors.state_estimator import StateEstimator
from agent_sensors.fusion_rules import infer_time_of_day

class TestPhase4EndToEnd(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.registry = SensorRegistry("agent_sensors/config/sensors.yaml")
        self.ingestion = SensorIngestion(self.event_bus, self.registry)
        self.estimator = StateEstimator(self.event_bus, self.registry)
        
        # Mock time for deterministic testing
        self.original_time = time.time
        self.current_sim_time = 1700000000.0 # Arbitrary start
        
    def tearDown(self):
        time.time = self.original_time

    def set_sim_time(self, hour: int, minute: int):
        # Set time to a specific hour/minute on the current day
        # We'll just use localtime of current_sim_time to preserve date, but change hour/min
        struct = time.localtime(self.current_sim_time)
        # Construct new timestamp
        # Simplified: just assume we are setting the hour of the day
        # But infer_time_of_day uses time.localtime(ts).tm_hour
        # So we just need to construct a TS that returns that hour.
        # Let's just mock time.localtime? No, infer_time_of_day calls it.
        # We can mock time.time() to return a TS that corresponds to that hour.
        
        # 2023-11-14 00:00:00 UTC is 1699920000
        # Let's just pick a base TS and add offsets.
        base_ts = 1700000000 # Tue Nov 14 2023 22:13:20 UTC
        # We want to force specific hour.
        # Let's just mock infer_time_of_day in the fusion rules? 
        # But we want to test fusion rules too.
        # So we need to mock time.time() globally.
        pass

    def test_scenario_1_normal_evening(self):
        """
        Scenario 1: Normal Evening
        - Motion in living_room
        - Lights on in living_room
        - Phone WiFi present
        - Time = 21:30 (Evening)
        """
        print("\n[Test] Scenario 1: Normal Evening")
        
        # 1. Set Time to 21:30 (Evening)
        mock_ts = 1700083800.0 # Tue Nov 15 2023 21:30:00 UTC
        
        # Use mock_ts for events so they are "recent"
        ts = mock_ts - 10.0 
        
        # WiFi Present
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": True, "ts": ts})
        
        # Motion Living Room
        self.ingestion.ingest_event({"sensor_id": "motion_living_main", "value": True, "ts": ts})
        
        # Light On Living Room
        self.ingestion.ingest_event({"sensor_id": "light_living_main", "value": 100, "ts": ts})
        
        # 2. Force Time of Day to Evening (via mock) AND mock time.time for OccupancySensor
        # We need to patch time.time globally so OccupancySensor sees it too.
        with unittest.mock.patch('time.time', return_value=mock_ts):
             with unittest.mock.patch('agent_sensors.state_estimator.infer_time_of_day', return_value="evening"):
                 self.estimator._update_situation()
             
        # 3. Verify
        situation = self.estimator.get_current_situation()
        
        self.assertEqual(situation.home_presence.state, "home")
        self.assertTrue(situation.room_occupancy["living_room"].is_occupied)
        self.assertEqual(situation.time_of_day, "evening")
        self.assertEqual(situation.sleep_state.state, "awake")
        self.assertEqual(situation.activity_hint, "relaxing") # Living room + Evening -> Relaxing
        print("✅ Scenario 1 Passed")

    def test_scenario_2_going_to_sleep(self):
        """
        Scenario 2: Going to Sleep
        - 22:45: lights dim in bedroom (simulated)
        - 23:10: lights off in bedroom, no motion
        """
        print("\n[Test] Scenario 2: Going to Sleep")
        
        ts = 100000.0
        
        # 1. WiFi Present
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": True, "ts": ts})
        
        # 2. Bedroom Motion (User enters)
        self.ingestion.ingest_event({"sensor_id": "motion_bedroom", "value": True, "ts": ts})
        
        # 3. Bedroom Lights Off
        # Mock registry for light_bedroom
        mock_sensor = MagicMock()
        mock_sensor.id = "light_bedroom"
        mock_sensor.type = "light_level"
        mock_sensor.room = "bedroom"
        self.registry.get_sensor = MagicMock(side_effect=lambda id: mock_sensor if id == "light_bedroom" else self.registry._sensors.get(id))
        
        self.ingestion.ingest_event({"sensor_id": "light_bedroom", "value": 0, "ts": ts})
        
        # 4. Advance time 30 mins (1800s)
        # Patch time.time globally for all sensors
        mock_now = ts + 1801
        
        with unittest.mock.patch('time.time', return_value=mock_now):
            with unittest.mock.patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                self.estimator._update_situation()
                
        situation = self.estimator.get_current_situation()
        
        self.assertEqual(situation.sleep_state.state, "sleeping")
        self.assertEqual(situation.activity_hint, "sleeping")
        print("✅ Scenario 2 Passed")

    def test_scenario_3_nobody_home(self):
        """
        Scenario 3: Nobody Home
        - WiFi Disconnect
        - Door Open/Close
        - No Motion > 2h
        """
        print("\n[Test] Scenario 3: Nobody Home")
        
        ts = 100000.0
        
        # 1. Door Open
        self.ingestion.ingest_event({"sensor_id": "contact_door_main", "value": True, "ts": ts})
        
        # 2. WiFi Disconnect
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": False, "ts": ts + 10})
        
        # 3. Advance time > 2 hours (7200s)
        mock_now = ts + 7300
        
        with unittest.mock.patch('time.time', return_value=mock_now):
            self.estimator._update_situation()
            
        situation = self.estimator.get_current_situation()
        
        self.assertEqual(situation.home_presence.state, "away")
        print("✅ Scenario 3 Passed")

    def test_scenario_4_midnight_snack(self):
        """
        Scenario 4: Midnight Snack
        - 01:30: bedroom occupancy true -> false (motion in kitchen)
        - 01:32: motion in kitchen + lights on
        """
        print("\n[Test] Scenario 4: Midnight Snack")
        
        ts = 100000.0
        
        # 1. WiFi Present
        self.ingestion.ingest_event({"sensor_id": "wifi_phone_user", "value": True, "ts": ts})
        
        # 2. Motion Kitchen
        self.ingestion.ingest_event({"sensor_id": "motion_kitchen", "value": True, "ts": ts})
        
        # 3. Light Kitchen On (Mock sensor)
        mock_sensor = MagicMock()
        mock_sensor.id = "light_kitchen"
        mock_sensor.type = "light_level"
        mock_sensor.room = "kitchen"
        self.registry.get_sensor = MagicMock(side_effect=lambda id: mock_sensor if id == "light_kitchen" else self.registry._sensors.get(id))
        
        self.ingestion.ingest_event({"sensor_id": "light_kitchen", "value": 100, "ts": ts})
        
        # 4. Time = Night
        # Patch time.time to be close to events so occupancy is active
        # Advance > 60s to bypass hysteresis check in StateEstimator
        mock_now = ts + 65.0
        
        with unittest.mock.patch('time.time', return_value=mock_now):
            with unittest.mock.patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                 self.estimator._update_situation()
                 
        situation = self.estimator.get_current_situation()
        
        self.assertEqual(situation.time_of_day, "night")
        self.assertTrue(situation.room_occupancy["kitchen"].is_occupied)
        self.assertEqual(situation.activity_hint, "snacking")
        print("✅ Scenario 4 Passed")

if __name__ == "__main__":
    unittest.main()
