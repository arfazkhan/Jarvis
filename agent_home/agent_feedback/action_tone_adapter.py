import random
from typing import Dict, Any, Optional

class ActionToneAdapter:
    """
    Adapts the tone of action confirmations based on context, urgency, and personality.
    """
    def __init__(self, personality_manager=None):
        self.personality_manager = personality_manager
        
        # Response Templates
        self.templates = {
            "casual": {
                "turn_on": ["Sure thing, turning on {device}.", "You got it, {device} on.", "Lights up!"],
                "turn_off": ["No problem, {device} off.", "Killing the {device}.", "Going dark."],
                "set_routine": ["Setting up {routine} mode.", "Let's get {routine} going."],
                "error": ["Oops, something went wrong.", "My bad, I couldn't do that."]
            },
            "formal": {
                "turn_on": ["Activating {device}.", "Turning on {device} as requested.", "Executing activation."],
                "turn_off": ["Deactivating {device}.", "Turning off {device}.", "Powering down {device}."],
                "set_routine": ["Initiating {routine} sequence.", "Configuring system for {routine}."],
                "error": ["I apologize, but I encountered an error.", "Unable to execute command."]
            },
            "urgent": {
                "turn_on": ["IMMEDIATE: Turning on {device}!", "Executing override for {device}."],
                "turn_off": ["CUTTING POWER to {device}!", "Emergency shutdown: {device}."],
                "error": ["CRITICAL FAILURE: Cannot execute.", "ALERT: Command failed."]
            }
        }

    def get_confirmation(self, action: str, params: Dict[str, Any], urgency: float = 0.0) -> str:
        """
        Get a context-aware confirmation message.
        
        Args:
            action: The intent/action name (e.g., "turn_on").
            params: Parameters for the action (e.g., {"device": "light"}).
            urgency: Float 0.0 to 1.0.
        """
        style = "casual" # Default
        
        # Determine style
        if urgency > 0.8:
            style = "urgent"
        elif self.personality_manager:
            # TODO: Fetch style from personality manager
            # For now, we'll stick to default or passed config
            pass
            
        # Get templates
        style_templates = self.templates.get(style, self.templates["casual"])
        options = style_templates.get(action, [f"Executing {action}."])
        
        # Select random option
        template = random.choice(options)
        
        # Format
        try:
            return template.format(**params)
        except KeyError:
            # Fallback if params missing
            return template.replace("{device}", params.get("device", "device")) \
                           .replace("{routine}", params.get("routine", "routine"))

