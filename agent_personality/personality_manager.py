"""
Personality Manager
-------------------
Central orchestrator for Phase 5.
Manages current persona, computes context, and integrates emotion.
"""

from typing import Dict, Any, Optional
import time

from agent.event_bus.event_bus import EventBus
from agent_sensors.sensor_models import HomeSituation, EmotionalState
from agent_personality.persona_profiles import PersonaProfiles, Persona
from agent_personality.emotion_engine import EmotionEngine

from agent_personality.mode_switcher import ModeSwitcher

class PersonalityManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.profiles = PersonaProfiles()
        self.emotion_engine = EmotionEngine()
        self.mode_switcher = ModeSwitcher()
        
        # State
        self.current_persona_id: str = self.profiles.get_default_persona()
        self.current_emotion: Optional[EmotionalState] = None
        
        # Subscribe to situation updates
        self.event_bus.subscribe("situation_update", self._on_situation_update)

    def _on_situation_update(self, event: Dict[str, Any]):
        """
        When situation updates:
        1. Re-infer emotion
        2. Publish personality_update (optional, or just store state)
        """
        pass

    def get_personality_context(self, situation: HomeSituation, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Called by DialogueManager/Planner to get personality context.
        """
        # 1. Infer Emotion
        emotion = self.emotion_engine.infer_emotion(situation)
        self.current_emotion = emotion
        
        # 2. Determine Persona (using ModeSwitcher)
        persona_id = self.mode_switcher.get_active_persona(user_id, situation, emotion)
        self.current_persona_id = persona_id
        
        persona = self.profiles.get_persona(persona_id)
        if not persona:
            persona = self.profiles.get_persona("neutral_assistant")
            
        # 3. Construct Context
        return {
            "persona": {
                "id": persona.id,
                "name": persona.name,
                "description": persona.description,
                "style_instructions": persona.style_instructions,
                "allowed_features": persona.allowed_features
            },
            "emotion": {
                "state": emotion.state,
                "confidence": emotion.confidence
            }
        }

    def set_user_preference(self, user_id: str, persona_id: str):
        self.mode_switcher.set_user_preference(user_id, persona_id)
