"""
Correction Detector
-------------------
Detects when a user action overrides a recent agent action.
"""

import time
from typing import Dict, Any, List, Optional, Tuple

class CorrectionDetector:
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self.agent_actions: List[Dict[str, Any]] = [] # History of agent actions

    def record_agent_action(self, action: Dict[str, Any]):
        """Record an action taken by the agent"""
        entry = {
            "action": action,
            "timestamp": time.time()
        }
        self.agent_actions.append(entry)
        self._cleanup()

    def detect_correction(self, user_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check if a user event corrects a recent agent action.
        User event: {type: "state_change", payload: {device_id, attribute, value, source="user"}}
        """
        if user_event.get("type") != "state_change":
            return None
            
        payload = user_event.get("payload", {})
        if payload.get("source") != "user":
            return None
            
        device_id = payload.get("device_id")
        attribute = payload.get("attribute")
        new_value = payload.get("value")
        
        # Look for recent agent action on same device/attribute
        for entry in reversed(self.agent_actions):
            agent_act = entry["action"]
            # Agent action structure: {action: "set_light", params: {device: "id", brightness: 50}}
            params = agent_act.get("params", {})
            
            if params.get("device") == device_id:
                # Check if attribute matches
                # Mapping needed: set_light -> brightness/color_temp
                # For MVP, assume simplistic mapping
                if self._is_attribute_relevant(agent_act["action"], attribute):
                    # Found a match!
                    return {
                        "type": "correction",
                        "original_action": agent_act,
                        "correction_event": user_event,
                        "category": self._get_category(agent_act["action"]),
                        "key": attribute,
                        "value": new_value
                    }
                    
        return None

    def _cleanup(self):
        """Remove old actions"""
        now = time.time()
        self.agent_actions = [a for a in self.agent_actions if now - a["timestamp"] < self.window_seconds]

    def _is_attribute_relevant(self, action: str, attribute: str) -> bool:
        if action == "set_light" and attribute in ["brightness", "color_temp", "state"]: return True
        if action in ["set_climate", "set_ac"] and attribute in ["temperature", "mode"]: return True
        if action == "play_media" and attribute in ["volume", "state"]: return True
        return False

    def _get_category(self, action: str) -> str:
        if action == "set_light": return "lighting"
        if action in ["set_climate", "set_ac"]: return "climate"
        if action == "play_media": return "media"
        return "unknown"
