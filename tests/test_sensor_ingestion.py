import unittest
from unittest.mock import MagicMock
from agent.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.sensor_ingestion import SensorIngestion

class TestSensorIngestion(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.event_bus.publish = MagicMock()
        
        # Mock Registry
        self.registry = SensorRegistry("agent_sensors/config/sensors.yaml")
        # We can mock get_sensor to avoid file dependency, but integration test is fine too.
        # Let's mock it for unit test isolation.
        self.registry.get_sensor = MagicMock()
        
        self.ingestion = SensorIngestion(self.event_bus, self.registry)

    def test_ingest_valid_event(self):
        # Setup mock sensor
        mock_sensor = MagicMock()
        mock_sensor.id = "motion_1"
        mock_sensor.type = "motion"
        mock_sensor.room = "living_room"
        self.registry.get_sensor.return_value = mock_sensor
        
        # Ingest
        self.ingestion.ingest_event({"sensor_id": "motion_1", "value": True})
        
        # Verify publish
        self.event_bus.publish.assert_called_once()
        args = self.event_bus.publish.call_args[0][0]
        self.assertEqual(args["type"], "sensor_event")
        self.assertEqual(args["payload"]["sensor_id"], "motion_1")
        self.assertEqual(args["payload"]["room"], "living_room")

    def test_ingest_unknown_sensor(self):
        self.registry.get_sensor.return_value = None
        
        self.ingestion.ingest_event({"sensor_id": "unknown", "value": True})
        
        self.event_bus.publish.assert_not_called()

if __name__ == "__main__":
    unittest.main()
