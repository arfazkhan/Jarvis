"""
Feedback Loop
-------------
Orchestrates the learning process.
1. Listens to events.
2. Uses CorrectionDetector to find corrections.
3. Uses PreferenceClassifier to classify signals.
4. Uses PreferenceUpdater to update store.
"""

from agent_feedback.correction_detector import CorrectionDetector
from agent_preferences.preference_classifier import PreferenceClassifier
from agent_preferences.preference_updater import PreferenceUpdater
from arvis_core.event_bus.event_bus import EventBus

class FeedbackLoop:
    def __init__(self, event_bus: EventBus, updater: PreferenceUpdater):
        self.event_bus = event_bus
        self.updater = updater
        self.detector = CorrectionDetector()
        self.classifier = PreferenceClassifier()
        
        # Subscribe to events
        self.event_bus.subscribe("action_execution", self._on_agent_action)
        self.event_bus.subscribe("state_change", self._on_state_change)
        self.event_bus.subscribe("explicit_preference", self._on_explicit_preference)

    def _on_agent_action(self, event):
        """Track agent actions"""
        payload = event.get("payload", {})
        if payload.get("status") == "completed":
            self.detector.record_agent_action(payload.get("action"))

    def _on_state_change(self, event):
        """Handle state changes (potential corrections or implicit prefs)"""
        # 1. Check for Correction
        correction = self.detector.detect_correction(event)
        if correction:
            print(f"[FeedbackLoop] Correction detected: {correction}")
            # Create a correction event/signal
            signal = self.classifier.classify({
                "type": "correction", 
                "payload": correction
            })
            self.updater.update(signal)
            return

        # 2. Check for Implicit Preference (if not a correction)
        signal = self.classifier.classify(event)
        if signal and signal.type == "implicit":
            self.updater.update(signal)

    def _on_explicit_preference(self, event):
        """Handle explicit voice preferences"""
        signal = self.classifier.classify(event)
        self.updater.update(signal)
