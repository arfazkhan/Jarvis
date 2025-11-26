"""
Emotion Engine
--------------
Infers functional emotional state from HomeSituation.
Heuristics-based for Phase 5.
"""

from typing import List
from agent_sensors.sensor_models import HomeSituation, EmotionalState

class EmotionEngine:
    def __init__(self):
        pass

    def infer_emotion(self, situation: HomeSituation) -> EmotionalState:
        """
        Map HomeSituation to EmotionalState.
        
        Heuristics:
        - Sleep=sleeping -> Calm (high conf)
        - Activity=relaxing + Evening -> Calm
        - Activity=working + Day -> Focused
        - Activity=snacking + Night -> Playful/Calm
        - Presence=Away -> Neutral
        """
        
        # Default
        label = "neutral"
        confidence = 0.5
        reasons = []
        
        # 1. Sleep State (Strongest signal)
        if situation.sleep_state.state == "sleeping":
            return EmotionalState(
                state="calm",
                confidence=0.9,
                updated_ts=situation.updated_ts
            )
        elif situation.sleep_state.state == "winding_down":
            return EmotionalState(
                state="calm",
                confidence=0.8,
                updated_ts=situation.updated_ts
            )
            
        # 2. Presence
        if situation.home_presence.state == "away":
            return EmotionalState(
                state="neutral",
                confidence=0.9,
                updated_ts=situation.updated_ts
            )
            
        # 3. Activity & Time
        activity = situation.activity_hint
        tod = situation.time_of_day
        
        if activity == "working":
            label = "focused"
            confidence = 0.7
            reasons.append("user is working")
            
        elif activity == "relaxing":
            label = "calm"
            confidence = 0.7
            reasons.append("user is relaxing")
            
        elif activity == "cooking":
            if tod == "morning":
                label = "focused" # Breakfast rush?
                confidence = 0.6
            else:
                label = "happy" # Cooking dinner?
                confidence = 0.5
                
        elif activity == "snacking":
            if tod == "night":
                label = "playful" # Midnight snack
                confidence = 0.6
                
        # 4. Time of Day Modifiers (if no strong activity)
        if label == "neutral":
            if tod == "night":
                label = "tired" # Assume tired at night if nothing else
                confidence = 0.4
            elif tod == "morning":
                label = "focused"
                confidence = 0.4
                
        return EmotionalState(
            state=label,
            confidence=confidence,
            updated_ts=situation.updated_ts
        )
