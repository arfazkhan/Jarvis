"""
Tone Adapter
------------
Adapts the raw text response to match the active persona and emotional context.
MVP: Rule-based modifiers and prefix/suffix injection.
Future: LLM-based rewriting.
"""

import random
from typing import List, Dict, Any
from agent_personality.persona_profiles import Persona
from agent_sensors.sensor_models import EmotionalState

class ToneAdapter:
    def __init__(self):
        pass

    def adapt_response(self, raw_text: str, persona: Persona, emotion: EmotionalState) -> str:
        """
        Modify raw_text to fit the persona and emotion.
        """
        final_text = raw_text
        
        # 1. Persona-based adaptation (Simple Heuristics for MVP)
        if persona.id == "jarvis_style":
            final_text = self._apply_jarvis_style(final_text)
        elif persona.id == "supportive_companion":
            final_text = self._apply_supportive_style(final_text)
        elif persona.id == "neutral_assistant":
            final_text = self._apply_neutral_style(final_text)
            
        # 2. Emotion-based adaptation
        if emotion.state == "tired":
            final_text = f"(Softly) {final_text}"
        elif emotion.state == "stressed":
            final_text = f"(Calmly) {final_text}"
        elif emotion.state == "playful":
            # Maybe add an emoji if allowed?
            if persona.allowed_features.get("humor") == "moderate":
                 final_text = f"{final_text} 😉"
                 
        return final_text

    def _apply_jarvis_style(self, text: str) -> str:
        # Jarvis is witty, formal but playful.
        # "I turned on the lights" -> "Lights are up, sir."
        # Simple replacements for demo
        replacements = {
            "I turned on": "Activated",
            "I turned off": "Deactivated",
            "Okay": "Very well, sir",
            "I don't know": "I'm afraid I lack that information",
            "Hello": "Greetings"
        }
        for k, v in replacements.items():
            if text.startswith(k):
                text = text.replace(k, v, 1)
        return text

    def _apply_supportive_style(self, text: str) -> str:
        # Supportive is warm, gentle.
        replacements = {
            "I turned on": "I've turned on",
            "I turned off": "I've switched off",
            "Okay": "Sure thing",
            "I don't know": "I'm not sure about that, sorry",
            "Hello": "Hi there"
        }
        for k, v in replacements.items():
            if text.startswith(k):
                text = text.replace(k, v, 1)
        return text

    def _apply_neutral_style(self, text: str) -> str:
        # Neutral is direct.
        replacements = {
            "I turned on": "Turning on",
            "I turned off": "Turning off",
            "Okay": "Done",
            "I don't know": "Unknown",
            "Hello": "Hello"
        }
        for k, v in replacements.items():
            if text.startswith(k):
                text = text.replace(k, v, 1)
        return text
