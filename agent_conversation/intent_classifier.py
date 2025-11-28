"""
Intent Classifier
-----------------
Classifies natural language text into system intents and extracts slots.
Uses regex-based heuristics for MVP (fast, local, no dependencies).
Future: Replace with BERT/Rasa/LLM.
"""

import re
from typing import Dict, Any, List, Optional

class IntentClassifier:
    def __init__(self):
        # Define simple regex patterns for common intents
        self.patterns = [
            {
                "intent": "start_mission",
                "regex": r"^start (?:the )?([\w\s]+?)(?: mission)?$",
                "slots": ["mission_type"]
            },
            {
                "intent": "stop_mission",
                "regex": r"^(?:stop|cancel|abort) (?:the )?(?:current )?mission$",
                "slots": []
            },
            {
                "intent": "mission_status",
                "regex": r"^mission status\?*$",
                "slots": []
            },
            {
                "intent": "turn_on",
                "regex": r"^turn on (?:the )?([\w\s]+?) in (?:the )?([\w\s]+)$",
                "slots": ["device", "location"]
            },
            {
                "intent": "turn_on",
                "regex": r"^turn on (?:the )?([\w\s]+)$",
                "slots": ["device"]
            },
            {
                "intent": "turn_off",
                "regex": r"^turn off (?:the )?([\w\s]+?) in (?:the )?([\w\s]+)$",
                "slots": ["device", "location"]
            },
            {
                "intent": "turn_off",
                "regex": r"^turn off (?:the )?([\w\s]+)$",
                "slots": ["device"]
            },
            {
                "intent": "set_routine",
                "regex": r"^(?:start|activate|enable) (?:the )?([\w\s]+)(?: mode| routine)?$",
                "slots": ["routine"]
            },
            {
                "intent": "query_status",
                "regex": r"^is (?:the )?([\w\s]+) (?:on|off|open|closed)\?*$",
                "slots": ["device"]
            },
            {
                "intent": "query_weather",
                "regex": r"^what(?:'s| is) the weather\?*$",
                "slots": []
            }
        ]

    def classify(self, text: str) -> Dict[str, Any]:
        """
        Classify text into intent and slots.
        Returns dict with intent, slots, and confidence.
        """
        text = text.lower().strip()
        
        for pattern in self.patterns:
            match = re.search(pattern["regex"], text)
            if match:
                slots = {}
                for i, slot_name in enumerate(pattern["slots"]):
                    # Regex groups start at 1
                    if i + 1 <= len(match.groups()):
                        val = match.group(i + 1)
                        if val:
                            slots[slot_name] = val
                            
                return {
                    "intent": pattern["intent"],
                    "slots": slots,
                    "confidence": 0.9,  # High confidence for regex match
                    "original_text": text
                }
                
        # Fallback
        return {
            "intent": "unknown",
            "slots": {},
            "confidence": 0.0,
            "original_text": text
        }
