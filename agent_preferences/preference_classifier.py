"""
Preference Classifier
---------------------
Classifies user interactions into preference signals.
Types:
1. Explicit: "I like the lights dim"
2. Implicit: User manually sets lights to 40%
3. Corrective: User changes lights immediately after Agent set them
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class PreferenceSignal:
    type: str # "explicit", "implicit", "corrective"
    category: str # "lighting", "climate", "media"
    key: str # "brightness", "temperature", "volume"
    value: Any
    confidence_delta: float

class PreferenceClassifier:
    def classify(self, event: Dict[str, Any]) -> Optional[PreferenceSignal]:
        """
        Classify an event into a preference signal.
        Event structure depends on source (voice, state_change, etc.)
        """
        event_type = event.get("type")
        payload = event.get("payload", {})
        
        # 1. Explicit Preference (from Voice/NLU)
        if event_type == "explicit_preference":
            return PreferenceSignal(
                type="explicit",
                category=payload.get("category"),
                key=payload.get("key"),
                value=payload.get("value"),
                confidence_delta=0.3
            )
            
        # 2. Corrective (from Feedback Loop)
        if event_type == "correction":
            return PreferenceSignal(
                type="corrective",
                category=payload.get("category"),
                key=payload.get("key"),
                value=payload.get("value"),
                confidence_delta=0.25
            )
            
        # 3. Implicit (from State Change)
        # If user manually changes state (not agent), it's implicit
        if event_type == "state_change" and payload.get("source") == "user":
            # Map device type to category
            device_type = payload.get("device_type")
            attr = payload.get("attribute")
            value = payload.get("value")
            
            category = self._map_type_to_category(device_type)
            if category and attr:
                return PreferenceSignal(
                    type="implicit",
                    category=category,
                    key=attr,
                    value=value,
                    confidence_delta=0.15
                )
                
        return None

    def _map_type_to_category(self, device_type: str) -> Optional[str]:
        if device_type in ["light", "lighting"]: return "lighting"
        if device_type in ["ac", "thermostat", "heater"]: return "climate"
        if device_type in ["speaker", "tv"]: return "media"
        return None
