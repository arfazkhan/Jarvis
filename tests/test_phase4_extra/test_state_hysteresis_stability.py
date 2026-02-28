import unittest
from unittest.mock import patch
import time

from arvis_core.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.sensor_ingestion import SensorIngestion
from agent_sensors.state_estimator import StateEstimator


class TestStateHysteresisStability(unittest.TestCase):

    def setUp(self):
        self.event_bus = EventBus()
        self.registry = SensorRegistry("agent_sensors/config/sensors.yaml")
        self.ingestion = SensorIngestion(self.event_bus, self.registry)
        self.estimator = StateEstimator(self.event_bus, self.registry)

    def test_state_hysteresis_prevents_oscillation(self):
        """
        Scenario:
        - User is sleeping (low activity, dark)
        - Brief kitchen motion occurs (e.g., cat or quick trip)
        - Without hysteresis: state flips to "snacking" then back to "sleep"
        - With hysteresis: ARVIS should remain consistent
        """

        print("\n[Test] State Hysteresis Stability")

        ts = 2000.0

        # Simulate: sleeping state
        self.estimator.sleep_sensor.bedroom_last_motion = ts - 3600
        self.estimator.sleep_sensor.bedroom_lights_on = False

        with patch('time.time', return_value=ts):
            with patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                self.estimator._update_situation()

        initial_state = self.estimator.get_current_situation().activity_hint
        self.assertEqual(initial_state, "sleeping")

        # Now: brief kitchen motion (should NOT override sleep)
        # We must patch time during ingestion because StateEstimator reacts immediately
        with patch('time.time', return_value=ts + 5):
            with patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                self.ingestion.ingest_event({
                    "sensor_id": "motion_kitchen",
                    "value": True,
                    "ts": ts + 5
                })

        # Update soon after
        with patch('time.time', return_value=ts + 10):
            with patch('agent_sensors.state_estimator.infer_time_of_day', return_value="night"):
                self.estimator._update_situation()

        new_state = self.estimator.get_current_situation().activity_hint

        # Should maintain sleeping due to hysteresis
        self.assertEqual(new_state, "sleeping")

        print("✅ Hysteresis prevented state oscillation (Sleeping → Snacking → Sleeping)")


if __name__ == "__main__":
    unittest.main()
