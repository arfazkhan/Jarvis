"""
Personality Manager
-------------------
Central orchestrator for Phase 5.
Manages current persona, computes context, and integrates emotion.
"""

from typing import Dict, Any, Optional
import time

from arvis_core.event_bus.event_bus import EventBus
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
        2. Publish personality_update
        """
        try:
            payload = event.get("payload", {})
            if not payload:
                return

            # Reconstruct HomeSituation from dict
            # We need to handle nested dataclasses manually since they come as dicts
            from agent_sensors.sensor_models import HomePresence, RoomOccupancy, SleepState, EmotionalState
            
            home_presence_data = payload.get("home_presence", {})
            home_presence = HomePresence(**home_presence_data)
            
            sleep_state_data = payload.get("sleep_state", {})
            sleep_state = SleepState(**sleep_state_data)
            
            emotional_state_data = payload.get("emotional_state", {})
            emotional_state = EmotionalState(**emotional_state_data)
            
            room_occupancy_data = payload.get("room_occupancy", {})
            room_occupancy = {k: RoomOccupancy(**v) for k, v in room_occupancy_data.items()}
            
            situation = HomeSituation(
                time_of_day=payload.get("time_of_day"),
                home_presence=home_presence,
                room_occupancy=room_occupancy,
                sleep_state=sleep_state,
                activity_hint=payload.get("activity_hint"),
                emotional_state=emotional_state,
                updated_ts=payload.get("updated_ts", time.time())
            )
            
            self.last_situation = situation
            
            # 1. Infer Emotion
            new_emotion = self.emotion_engine.infer_emotion(situation)
            self.current_emotion = new_emotion
            
            # 2. Determine Persona
            # We use default user for now
            new_persona_id = self.mode_switcher.get_active_persona("default_user", situation, new_emotion)
            
            if new_persona_id != self.current_persona_id:
                print(f"[PersonalityManager] Switching persona: {self.current_persona_id} -> {new_persona_id}")
                self.current_persona_id = new_persona_id
                
                # Publish update
                self.event_bus.publish({
                    "type": "personality_update",
                    "source": "personality_manager",
                    "payload": {
                        "persona_id": new_persona_id,
                        "emotion": new_emotion.state,
                        "confidence": new_emotion.confidence
                    }
                })
                
        except Exception as e:
            print(f"[PersonalityManager] Error processing situation update: {e}")

    def get_personality_context(self, situation: Optional[HomeSituation] = None, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Called by DialogueManager/Planner to get personality context.
        """
        # Use cached situation if not provided
        if not situation:
            situation = getattr(self, "last_situation", None)
            
        # If still no situation (startup), use defaults
        if not situation:
             # Return default/neutral context
             persona = self.profiles.get_persona(self.current_persona_id)
             return {
                "persona": {
                    "id": persona.id,
                    "name": persona.name,
                    "description": persona.description,
                    "style_instructions": persona.style_instructions,
                    "allowed_features": persona.allowed_features
                },
                "emotion": {"state": "neutral", "confidence": 0.5}
            }

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
