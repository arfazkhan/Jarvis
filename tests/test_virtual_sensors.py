import unittest
import time
from unittest.mock import patch
from agent_sensors.sensor_models import SensorEvent
from agent_sensors.virtual_sensors.occupancy_sensor import OccupancySensor
from agent_sensors.virtual_sensors.presence_sensor import PresenceSensor
from agent_sensors.virtual_sensors.sleep_sensor import SleepSensor

class TestVirtualSensors(unittest.TestCase):
    
    # --- Occupancy ---
    def test_occupancy_motion(self):
        sensor = OccupancySensor(timeout_seconds=100)
        
        # Motion Event
        event = SensorEvent("m1", "motion", "living_room", True, time.time())
        sensor.update_from_event(event)
        
        occ = sensor.get_room_occupancy("living_room")
        self.assertTrue(occ.is_occupied)
        self.assertEqual(occ.confidence, 1.0)
        
    def test_occupancy_timeout(self):
        sensor = OccupancySensor(timeout_seconds=100)
        
        # Old Motion
        old_ts = time.time() - 200
        event = SensorEvent("m1", "motion", "living_room", True, old_ts)
        sensor.update_from_event(event)
        
        occ = sensor.get_room_occupancy("living_room")
        self.assertFalse(occ.is_occupied)
        self.assertEqual(occ.confidence, 0.0)

    # --- Presence ---
    def test_presence_wifi(self):
        sensor = PresenceSensor()
        
        # Mock time
        base_time = 100000.0
        
        with patch('time.time', return_value=base_time):
            # WiFi Connect
            event = SensorEvent("wifi_1", "wifi_presence", None, True, base_time)
            sensor.update_from_event(event)
            
            presence = sensor.get_home_presence()
            self.assertEqual(presence.state, "home")
            self.assertIn("wifi_1", presence.sources)
            
            # WiFi Disconnect
            event_off = SensorEvent("wifi_1", "wifi_presence", None, False, base_time)
            sensor.update_from_event(event_off)
        
        # Advance time > 60s (grace period)
        with patch('time.time', return_value=base_time + 65.0):
            presence = sensor.get_home_presence()
            # Should be unknown or home (short timeout)
            # But we had no motion (ts=0). So > 2 hours -> away.
            self.assertEqual(presence.state, "away")

    # --- Sleep ---
    def test_sleep_inference(self):
        sensor = SleepSensor()
        
        # 1. Night time, no motion for long time
        # Simulate motion 1 hour ago
        sensor.bedroom_last_motion = time.time() - 3600 
        sensor.bedroom_lights_on = False
        
        state = sensor.calculate_state("night")
        self.assertEqual(state.state, "sleeping")
        self.assertTrue(state.confidence > 0.8)
        
        # 2. Morning, recent motion
        sensor.bedroom_last_motion = time.time()
        state = sensor.calculate_state("morning")
        self.assertEqual(state.state, "awake")

if __name__ == "__main__":
    unittest.main()
