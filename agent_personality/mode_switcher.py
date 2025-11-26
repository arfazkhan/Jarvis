"""
Mode Switcher
-------------
Determines the active persona based on:
1. User preference (explicit setting)
2. Context overrides (e.g., late night, high stress)
"""

from typing import Dict, Optional
from agent_sensors.sensor_models import HomeSituation, EmotionalState

class ModeSwitcher:
    def __init__(self):
        # In-memory preference store for MVP
        # In real app, this would be backed by a DB
        self.user_preferences: Dict[str, str] = {} 
        self.default_persona = "jarvis_style"

    def set_user_preference(self, user_id: str, persona_id: str):
        self.user_preferences[user_id] = persona_id
        print(f"User {user_id} preference set to {persona_id}")

    def get_active_persona(self, user_id: str, situation: HomeSituation, emotion: EmotionalState) -> str:
        """
        Decide which persona to use.
        Priority:
        1. Safety/Context Overrides (e.g. Emergency, Sleep)
        2. User Preference
        3. Default
        """
        
        # 1. Context Overrides
        
        # Sleep Override: If user is sleeping/winding down, be gentle (Supportive)
        # unless user specifically asked for Neutral.
        # Let's say Sleep -> Supportive (gentle) is a good default override for Jarvis.
        if situation.sleep_state.state in ["sleeping", "winding_down"]:
            # If user prefers Neutral, keep Neutral (it's quiet).
            # If user prefers Jarvis, downgrade to Supportive (less witty, more soft).
            preferred = self.user_preferences.get(user_id, self.default_persona)
            if preferred == "jarvis_style":
                return "supportive_companion"
                
        # Stress Override: If user is stressed, avoid wit.
        if emotion.state == "stressed":
            return "supportive_companion"
            
        # 2. User Preference
        return self.user_preferences.get(user_id, self.default_persona)
