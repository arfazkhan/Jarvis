import unittest
import time
from unittest.mock import patch

from arvis_core.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.sensor_ingestion import SensorIngestion
from agent_sensors.state_estimator import StateEstimator


class TestEmotionLowSignalNeutrality(unittest.TestCase):

    def setUp(self):
        self.event_bus = EventBus()
        self.registry = SensorRegistry("agent_sensors/config/sensors.yaml")
        self.ingestion = SensorIngestion(self.event_bus, self.registry)
        self.estimator = StateEstimator(self.event_bus, self.registry)

    def test_emotion_low_signal_should_be_neutral(self):
        """
        Scenario:
        - Dim lights (soft ambiance)
        - No motion (quiet user)
        - Evening time
        These signals individually COULD imply rest or sadness,
        but ARVIS should NOT infer an emotion from them alone.
        """

        print("\n[Test] Emotion Neutrality - Weak Signals")

        ts = 1000.0

        # 1. Light is dim (common, not emotional on its own)
        self.ingestion.ingest_event({
            "sensor_id": "light_living_main",
            "value": 20,  # dim
            "ts": ts
        })

        # 2. No motion for a while (quiet user)
        mock_now = ts + 300  # 5 minutes

        with patch('time.time', return_value=mock_now):
            self.estimator._update_situation()

        situation = self.estimator.get_current_situation()

        # Emotional inference will be part of Phase 5
        # For Phase 4, emotional_state should always be neutral
        # unless fused signals STRONGLY indicate otherwise.
        emotional_state = situation.emotional_state.state
        confidence = situation.emotional_state.confidence

        self.assertEqual(emotional_state, "neutral")
        self.assertLess(confidence, 0.3)  # Weak confidence

        print("✅ Weak signals correctly treated as NEUTRAL emotion")


if __name__ == "__main__":
    unittest.main()
