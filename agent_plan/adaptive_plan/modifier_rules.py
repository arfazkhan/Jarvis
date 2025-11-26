"""
Modifier Rules
--------------
Functions to apply preferences to specific action types.
"""

from typing import Dict, Any

def apply_lighting_prefs(step: Dict[str, Any], prefs: Dict[str, Any]):
    """Apply lighting preferences (brightness, color_temp)"""
    params = step.get("params", {})
    
    # Brightness
    if "brightness" in prefs:
        # Only override if the plan doesn't have a specific "forced" flag?
        # Or just override. For MVP, we override default-ish values.
        # But if user said "Set lights to 100%", we shouldn't override with 50%.
        # How do we know?
        # The plan step might come from a Scene (generic) or Custom (specific).
        # If it's a Scene, we should override.
        # If it's Custom, maybe not?
        # For now, we apply preferences if they exist.
        params["brightness"] = prefs["brightness"]["value"]
        
    # Color Temp
    if "color_temp" in prefs:
        params["color_temp"] = prefs["color_temp"]["value"]
        
    step["params"] = params

def apply_climate_prefs(step: Dict[str, Any], prefs: Dict[str, Any]):
    """Apply climate preferences (temperature)"""
    params = step.get("params", {})
    
    if "temperature" in prefs:
        params["temperature"] = prefs["temperature"]["value"]
        
    step["params"] = params

def apply_media_prefs(step: Dict[str, Any], prefs: Dict[str, Any]):
    """Apply media preferences (volume)"""
    params = step.get("params", {})
    
    if "volume" in prefs:
        params["volume"] = prefs["volume"]["value"]
        
    step["params"] = params

MODIFIERS = {
    "set_light": apply_lighting_prefs,
    "set_climate": apply_climate_prefs,
    "set_ac": apply_climate_prefs,
    "play_media": apply_media_prefs
}
