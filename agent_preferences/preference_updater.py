"""
Preference Updater
------------------
Updates the PreferenceStore based on signals.
Handles confidence weighting and merging.
"""

from agent_preferences.preference_store import PreferenceStore
from agent_preferences.preference_classifier import PreferenceSignal

class PreferenceUpdater:
    def __init__(self, store: PreferenceStore):
        self.store = store

    def update(self, signal: PreferenceSignal):
        """
        Update preference based on signal.
        New Confidence = Old * 0.7 + Signal
        """
        if not signal:
            return

        # Get existing preference
        current = self.store.get(signal.category, signal.key)
        
        old_conf = current["confidence"] if current else 0.0
        old_val = current["value"] if current else None
        
        # Calculate new confidence
        # If value matches, boost confidence
        # If value differs, reduce old confidence (implicit in formula if we overwrite)
        
        # Simple formula: decay old, add new signal
        # But if value is same, we should reinforce?
        # If value is different, we overwrite?
        
        if old_val == signal.value:
            # Reinforce
            new_conf = min(1.0, old_conf + signal.confidence_delta)
        else:
            # Overwrite with mixed confidence
            # If signal is strong enough, it takes over.
            # If signal is weak and old is strong, maybe we don't overwrite?
            # For MVP, we overwrite but blend confidence.
            new_conf = (old_conf * 0.7) + signal.confidence_delta
            new_conf = min(1.0, new_conf)
            
        self.store.set(signal.category, signal.key, signal.value, new_conf)
        print(f"[PreferenceUpdater] Updated {signal.category}.{signal.key} = {signal.value} (Conf: {new_conf:.2f})")
