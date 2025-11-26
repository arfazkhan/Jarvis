"""
Safety Policies
---------------
Guardrails to prevent inappropriate or unsafe content.
Blocks over-familiarity, medical advice, and harmful content.
"""

import yaml
from typing import List, Dict, Optional

class SafetyPolicies:
    def __init__(self, config_path: str = "config/personality/safety_blocks.yaml"):
        self.blocked_topics: List[str] = []
        self.blocked_phrases: List[str] = []
        self.redirect_messages: Dict[str, str] = {}
        self._load_config(config_path)

    def _load_config(self, path: str):
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                safety = data.get("safety_blocks", {})
                self.blocked_topics = safety.get("blocked_topics", [])
                self.blocked_phrases = safety.get("blocked_phrases", [])
                self.redirect_messages = safety.get("redirect_messages", {})
        except FileNotFoundError:
            print(f"Warning: Safety config not found at {path}")
        except Exception as e:
            print(f"Error loading safety policies: {e}")

    def check_response(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Check if response is safe.
        Returns: (is_safe, redirect_message)
        """
        text_lower = text.lower()
        
        # 1. Check blocked phrases
        for phrase in self.blocked_phrases:
            if phrase.lower() in text_lower:
                return (False, "I apologize, but I'm not able to respond that way.")
        
        # 2. Check blocked topics (medical, legal, etc.)
        for topic in self.blocked_topics:
            if topic.lower() in text_lower:
                # Find appropriate redirect
                if "medical" in topic or "diagnosis" in topic:
                    return (False, self.redirect_messages.get("medical", "I cannot provide medical advice."))
                elif "mental" in topic or "self-harm" in topic or "suicide" in topic:
                    return (False, self.redirect_messages.get("mental_health", "Please reach out to a professional."))
                else:
                    return (False, "I'm not able to help with that topic.")
        
        return (True, None)

    def filter_response(self, text: str) -> str:
        """
        Apply safety filter to response.
        Returns sanitized text or redirect message.
        """
        is_safe, redirect = self.check_response(text)
        if not is_safe:
            return redirect
        return text
