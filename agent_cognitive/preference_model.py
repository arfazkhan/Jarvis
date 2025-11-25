"""
Preference Model
----------------
Tracks user preferences with confidence scores and decay.
Learns from explicit feedback and implicit behavior.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from config.settings import get_config

CONFIG = get_config("cognitive")
STORAGE_PATH = Path("data/cognitive/preferences.json")

class PreferenceModel:
    def __init__(self):
        self.storage_path = STORAGE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.preferences = {}  # {user_id: {key: {value, confidence, last_updated}}}
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    self.preferences = json.load(f)
            except Exception:
                self.preferences = {}

    def _save(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.preferences, f, indent=2)

    def set_preference(self, user_id: str, key: str, value: Any, confidence: float = 1.0):
        """
        Explicitly set a preference.
        Confidence defaults to 1.0 for explicit user settings.
        """
        if user_id not in self.preferences:
            self.preferences[user_id] = {}
            
        self.preferences[user_id][key] = {
            "value": value,
            "confidence": confidence,
            "last_updated": time.time(),
            "source": "explicit" if confidence == 1.0 else "learned"
        }
        self._save()

    def get_preference(self, user_id: str, key: str) -> Optional[Any]:
        """Get a preference value if it exists"""
        user_prefs = self.preferences.get(user_id, {})
        pref = user_prefs.get(key)
        if pref:
            return pref["value"]
        return None

    def learn_from_event(self, user_id: str, event_type: str, payload: Dict[str, Any]):
        """
        Update preferences based on observed behavior.
        Simple heuristic learning (MVP).
        """
        # Example: User sets thermostat -> learn temperature preference
        if event_type == "set_temperature":
            temp = payload.get("temperature")
            if temp:
                # We verify if this is a repeated behavior in a real ML model
                # For MVP, we just update with lower confidence
                current = self.preferences.get(user_id, {}).get("preferred_temp", {})
                current_conf = current.get("confidence", 0.0)
                
                # Reinforcement learning-ish update
                new_conf = min(0.9, current_conf + 0.1)
                
                self.set_preference(user_id, "preferred_temp", temp, confidence=new_conf)

    def get_all_preferences(self, user_id: str) -> Dict[str, Any]:
        """Return all preferences for a user"""
        return self.preferences.get(user_id, {})
