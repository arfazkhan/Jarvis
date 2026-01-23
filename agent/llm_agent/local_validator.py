"""
LocalAgent Validation Layer v2
Balanced pre/post validation - catch hallucinations without blocking valid commands.
"""

import re
from typing import Dict, List, Optional, Tuple

# PRE-VALIDATION: Only catch OBVIOUS escalation cases
# These patterns are very specific to avoid false positives
ESCALATE_PATTERNS_STRICT = [
    # Exact ambiguous phrases (not containing device names)
    r"^(the\s+)?lights?$",  # Just "lights" or "light" alone
    r"^on$|^off$",  # Just "on" or "off" alone
    
    # Pure room-only (no "light/fan/ac" keyword at all)
    r"^(turn\s+on|turn\s+off)\s+the\s+(kitchen|bedroom|bathroom|living\s+room|garage)$",
    
    # Questions (end with ?)
    r"\?$",
    
    # Scene/mode keywords
    r"\b(movie\s+mode|night\s+mode|bedtime\s+mode|morning\s+mode)\b",
    
    # Multi-device explicit
    r"\ball\s+(lights|devices)\b",
    r"\beverything\b",
    
    # Cancel/stop explicit
    r"^(stop|cancel|nevermind)$",
    
    # Greetings only (nothing else)
    r"^(hey|hi|hello|arvis|hey\s+arvis)$",
    
    # Brightness/dim keywords
    r"\b(dim\s+to|set.*\d+%|brighter|dimmer)\b",
]


def pre_validate(user_input: str) -> Tuple[bool, Optional[str]]:
    """
    Conservative pre-validation - only catch OBVIOUS cases.
    Let LLM handle edge cases.
    """
    text = user_input.lower().strip()
    
    # Empty or too short
    if not text or len(text) < 2:
        return True, "empty_or_too_short"
    
    # Check strict escalation patterns only
    for pattern in ESCALATE_PATTERNS_STRICT:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"strict_pattern: {pattern[:30]}"
    
    return False, None


def post_validate(
    tool_call: Dict,
    user_input: str,
    known_devices: List[str]
) -> Tuple[bool, Dict, Optional[str]]:
    """
    Post-validation - catch LLM hallucinations.
    More aggressive than pre-validation since LLM has already made a decision.
    """
    tool_name = tool_call.get("tool", "")
    args = tool_call.get("args", {})
    device_id = args.get("device_id", "")
    
    text_lower = user_input.lower()
    
    # If LLM chose escalate, trust it
    if tool_name == "escalate":
        return True, tool_call, None
    
    # If LLM chose log_memory, validate and allow it
    if tool_name == "log_memory":
        args = tool_call.get("args", {})
        if args.get("key") and args.get("value"):
            return True, tool_call, None
        return False, {"tool": "escalate", "args": {}}, "log_memory_missing_args"
    
    # Validate tool name
    if tool_name not in ("turn_on", "turn_off"):
        return False, {"tool": "escalate", "args": {}}, f"invalid_tool: {tool_name}"
    
    # Check if user input actually contains a device-like word
    device_keywords = ["light", "lamp", "fan", "ac", "tv", "heater", "switch"]
    has_device_keyword = any(kw in text_lower for kw in device_keywords)
    
    # Special case: exact device names like "ac", "tv"
    exact_devices = ["ac", "tv", "fan"]
    has_exact_device = any(d in text_lower.split() for d in exact_devices)
    
    if not has_device_keyword and not has_exact_device:
        # No device keyword found - this is suspicious
        # But check if known devices might match
        device_mentioned = False
        for device in known_devices:
            if device.lower().replace("_", " ") in text_lower:
                device_mentioned = True
                break
        
        if not device_mentioned:
            return False, {"tool": "escalate", "args": {}}, "no_device_keyword"
    
    # Check if room-only request (device_id is just a room name)
    room_only_patterns = ["kitchen", "bedroom", "bathroom", "living room", "garage"]
    if device_id.lower() in room_only_patterns:
        return False, {"tool": "escalate", "args": {}}, "room_only_no_device"
    
    return True, {"tool": tool_name, "args": args}, None


def validate_and_correct(
    llm_result: List[Dict],
    user_input: str,
    known_devices: List[str]
) -> List[Dict]:
    """Full validation pipeline."""
    # Pre-validation (conservative)
    should_escalate, reason = pre_validate(user_input)
    if should_escalate:
        print(f"[Validator] Pre-escalate: {reason}")
        return [{"tool": "escalate", "args": {}}]
    
    # If LLM returned nothing, escalate
    if not llm_result:
        print("[Validator] LLM returned None, escalating")
        return [{"tool": "escalate", "args": {}}]
    
    # Post-validate each tool call
    validated_calls = []
    for call in llm_result:
        is_valid, corrected, reason = post_validate(call, user_input, known_devices)
        if not is_valid:
            print(f"[Validator] Post-correction: {reason}")
        validated_calls.append(corrected)
    
    return validated_calls
