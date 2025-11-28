import unittest
from agent_sensors.sensor_models import Sensor, SensorEvent, HomeSituation, HomePresence, RoomOccupancy, SleepState, EmotionalState

class TestSensorModels(unittest.TestCase):
    def test_sensor_event_serialization(self):
        event = SensorEvent(
            sensor_id="motion_1",
            sensor_type="motion",
            room="living_room",
            value=True,
            ts=1234567890.0
        )
        data = event.as_dict()
        self.assertEqual(data["sensor_id"], "motion_1")
        self.assertEqual(data["value"], True)
        self.assertEqual(data["ts"], 1234567890.0)

    def test_home_situation_serialization(self):
        presence = HomePresence(state="home", confidence=0.9, sources=["wifi"])
        occupancy = {"living_room": RoomOccupancy(room="living_room", is_occupied=True, confidence=0.8, last_change_ts=0)}
        sleep = SleepState(state="awake", confidence=1.0, since_ts=0)
        
        situation = HomeSituation(
            time_of_day="evening",
            home_presence=presence,
            room_occupancy=occupancy,
            sleep_state=sleep,
            activity_hint="relaxing",
            emotional_state=EmotionalState("neutral", 0.1, 1000.0),
            updated_ts=1000.0
        )
        
        data = situation.to_dict()
        self.assertEqual(data["time_of_day"], "evening")
        self.assertEqual(data["home_presence"]["state"], "home")
        self.assertEqual(data["room_occupancy"]["living_room"]["is_occupied"], True)

if __name__ == "__main__":
    unittest.main()
