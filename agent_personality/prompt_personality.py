"""
Prompt Personality
-----------------
Wraps LLM prompts with personality, emotion, and safety constraints.
Enhances the planning prompt with context-aware instructions.
"""

from typing import Dict, Any
from agent_sensors.sensor_models import HomeSituation

def build_personality_prompt(
    persona_context: Dict[str, Any],
    situation: HomeSituation
) -> str:
    """
    Build the personality section of the system prompt.
    
    Args:
        persona_context: Output from PersonalityManager.get_personality_context()
        situation: Current HomeSituation
    
    Returns:
        Formatted prompt section
    """
    persona = persona_context["persona"]
    emotion = persona_context["emotion"]
    
    # Build style instructions
    style_instructions = "\n  ".join(persona["style_instructions"])
    
    # Build allowed features
    features = persona["allowed_features"]
    feature_text = []
    if features.get("smalltalk"):
        feature_text.append("You may engage in light small talk when appropriate.")
    else:
        feature_text.append("Avoid small talk; stay focused on tasks.")
        
    if features.get("reflections"):
        feature_text.append("You may reference past actions or patterns to provide context.")
    else:
        feature_text.append("Do not reference past interactions.")
        
    humor_level = features.get("humor", "none")
    if humor_level == "moderate":
        feature_text.append("You may use light wit or playful language.")
    elif humor_level == "light":
        feature_text.append("You may use very subtle humor sparingly.")
    else:
        feature_text.append("Avoid humor or jokes entirely.")
    
    features_str = "\n- ".join(feature_text)
    
    # Build emotional context
    emotion_guidance = ""
    if emotion["state"] == "tired":
        emotion_guidance = "User seems tired. Keep responses brief and gentle."
    elif emotion["state"] == "stressed":
        emotion_guidance = "User may be stressed. Be calming and avoid suggestions unless critical."
    elif emotion["state"] == "playful":
        emotion_guidance = "User seems relaxed. You may be slightly more conversational."
    elif emotion["state"] == "calm":
        emotion_guidance = "User is calm. Maintain a balanced tone."
    elif emotion["state"] == "focused":
        emotion_guidance = "User is focused. Be efficient and avoid distractions."
    
    # Build situation awareness
    presence = situation.home_presence.state
    activity = situation.activity_hint or "unknown"
    sleep = situation.sleep_state.state
    
    situation_text = f"""
HOME CONTEXT:
- Presence: {presence}
- Activity: {activity}
- Sleep State: {sleep}
- Emotional Inference: {emotion["state"]} (confidence: {emotion["confidence"]:.2f})
"""
    
    # Assemble full prompt section
    prompt = f"""
PERSONA: {persona["name"]}
{persona["description"]}

STYLE INSTRUCTIONS:
  {style_instructions}

ALLOWED FEATURES:
- {features_str}

{situation_text}

EMOTIONAL GUIDANCE:
{emotion_guidance}

SAFETY CONSTRAINTS:
- NEVER provide medical, legal, or financial advice.
- NEVER use overly familiar language (e.g., "I love you", "I need you").
- NEVER simulate emotions you don't have; instead, acknowledge the user's state.
- If the user seems distressed, soften your tone and avoid complex suggestions.
- Emergency messages override persona (stay clear and direct).
"""
    
    return prompt


def build_full_system_prompt(
    persona_context: Dict[str, Any],
    situation: HomeSituation,
    base_prompt: str = ""
) -> str:
    """
    Combine base planning prompt with personality prompt.
    
    Args:
        persona_context: Personality context from PersonalityManager
        situation: Current HomeSituation
        base_prompt: Existing system prompt (from prompt_planning.py)
    
    Returns:
        Complete system prompt
    """
    personality_section = build_personality_prompt(persona_context, situation)
    
    # Combine
    full_prompt = f"""{base_prompt}

-----------------------------------------------------------
PERSONALITY & CONTEXT
-----------------------------------------------------------
{personality_section}
"""
    
    return full_prompt
