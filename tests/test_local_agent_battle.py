"""
LocalAgent Battle Test Suite
Comprehensive test cases for Qwen 3B tool calling accuracy.
"""

import json
import time
from typing import List, Dict, Tuple

# Test case structure: (input, expected_tool, expected_device_pattern, description)
TEST_CASES = [
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 1: Simple device commands (should handle locally)
    # ═══════════════════════════════════════════════════════════
    ("Turn on kitchen light", "turn_on", "kitchen", "Basic turn on"),
    ("Turn off bedroom light", "turn_off", "bedroom", "Basic turn off"),
    ("Turn on the living room light", "turn_on", "living", "With article 'the'"),
    ("Turn off the bathroom light", "turn_off", "bathroom", "With article"),
    ("Kitchen light on", "turn_on", "kitchen", "Inverted order"),
    ("Bedroom light off", "turn_off", "bedroom", "Inverted order"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 2: Polite phrasing (should still handle locally)
    # ═══════════════════════════════════════════════════════════
    ("Please turn on kitchen light", "turn_on", "kitchen", "With 'please'"),
    ("Can you turn off bedroom light", "turn_off", "bedroom", "With 'can you'"),
    ("Could you turn on porch light", "turn_on", "porch", "With 'could you'"),
    ("Hey turn on tv light", "turn_on", "tv", "With 'hey'"),
    ("Would you turn off garage light", "turn_off", "garage", "With 'would you'"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 3: Underscore device names (exact match)
    # ═══════════════════════════════════════════════════════════
    ("Turn on kitchen_main", "turn_on", "kitchen_main", "Underscore device"),
    ("Turn off living_room_light", "turn_off", "living_room_light", "Underscore device"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 4: Non-light devices
    # ═══════════════════════════════════════════════════════════
    ("Turn on the ac", "turn_on", "ac", "AC device"),
    ("Turn off the fan", "turn_off", "fan", "Fan device"),
    ("Turn on the heater", "turn_on", "heater", "Heater device"),
    ("Turn off tv", "turn_off", "tv", "TV device"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 5: Ambiguous commands (MUST escalate)
    # ═══════════════════════════════════════════════════════════
    ("Turn on the lights", "escalate", None, "Ambiguous - which lights?"),
    ("Turn it on", "escalate", None, "No device mentioned"),
    ("Turn on", "escalate", None, "No device at all"),
    ("Lights on", "escalate", None, "Ambiguous lights"),
    ("Turn off all lights", "escalate", None, "Multi-device command"),
    ("Switch on the light", "escalate", None, "Ambiguous 'the light'"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 6: Complex commands (MUST escalate)
    # ═══════════════════════════════════════════════════════════
    ("Set up movie mode", "escalate", None, "Complex/scene request"),
    ("Make it brighter", "escalate", None, "Brightness adjustment"),
    ("Dim the lights to 50%", "escalate", None, "Dimming request"),
    ("Set the bedroom light to warm", "escalate", None, "Color temp request"),
    ("Turn on all devices", "escalate", None, "Multi-device"),
    ("Create a morning routine", "escalate", None, "Routine creation"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 7: Questions (MUST escalate)
    # ═══════════════════════════════════════════════════════════
    ("Is the kitchen light on?", "escalate", None, "Question"),
    ("What lights are on?", "escalate", None, "Status query"),
    ("Are any lights on?", "escalate", None, "Status query"),
    ("How bright is the bedroom?", "escalate", None, "State query"),
    
    # ═══════════════════════════════════════════════════════════
    # CATEGORY 8: Edge cases
    # ═══════════════════════════════════════════════════════════
    ("", "escalate", None, "Empty input"),
    ("hello", "escalate", None, "Greeting"),
    ("thank you", "escalate", None, "Gratitude"),
    ("what time is it", "escalate", None, "Time query"),
    ("good morning", "escalate", None, "Greeting"),
    ("Turn on kitchen light and bedroom light", "escalate", None, "Multi-device in one command"),
]

# Known devices for the test
KNOWN_DEVICES = [
    "kitchen light", "kitchen_main", "bedroom light", "living room light",
    "living_room_light", "bathroom light", "porch light", "tv light",
    "garage light", "ac", "fan", "heater", "tv"
]

# Simplified tool schema for LocalAgent
TOOLS_SCHEMA = [
    {"name": "turn_on", "description": "Turn on a device"},
    {"name": "turn_off", "description": "Turn off a device"},
    {"name": "escalate", "description": "Escalate to cloud LLM"},
]


def run_test(local_agent, test_input: str, expected_tool: str, 
             expected_device: str, description: str) -> Tuple[bool, str]:
    """
    Run a single test case.
    Returns (passed: bool, details: str)
    """
    try:
        result = local_agent.generate_tool_call(
            user_input=test_input,
            tools_schema=TOOLS_SCHEMA,
            known_devices=KNOWN_DEVICES
        )
        
        if result is None:
            if expected_tool == "escalate":
                return True, "✅ Correctly returned None (implicit escalate)"
            return False, f"❌ Got None, expected {expected_tool}"
        
        # Extract tool name
        actual_tool = result[0].get("tool", "unknown") if result else "none"
        actual_device = result[0].get("args", {}).get("device_id", "") if result else ""
        
        # Check tool match
        tool_match = actual_tool == expected_tool
        
        # Check device match (if applicable)
        device_match = True
        if expected_device and expected_tool != "escalate":
            device_match = expected_device.lower() in actual_device.lower()
        
        if tool_match and device_match:
            return True, f"✅ {actual_tool}({actual_device})"
        elif tool_match and not device_match:
            return False, f"⚠️ Tool OK but device wrong: got '{actual_device}', expected contains '{expected_device}'"
        else:
            return False, f"❌ Got {actual_tool}({actual_device}), expected {expected_tool}({expected_device or 'N/A'})"
            
    except Exception as e:
        return False, f"💥 Error: {e}"


def run_all_tests(local_agent):
    """Run all test cases and report results."""
    print("\n" + "="*70)
    print("LOCALAGENT BATTLE TEST - Qwen 3B Tool Calling Accuracy")
    print("="*70)
    
    results = {"passed": 0, "failed": 0, "total": len(TEST_CASES)}
    category_results = {}
    failed_tests = []
    
    current_category = ""
    
    for i, (test_input, expected_tool, expected_device, description) in enumerate(TEST_CASES):
        # Detect category changes
        if "CATEGORY" in description or description.startswith("Basic"):
            if "Basic" in description:
                current_category = "Simple Commands"
            elif "please" in description.lower() or "can you" in description.lower():
                current_category = "Polite Phrasing"
        
        # Initialize category
        if current_category not in category_results:
            category_results[current_category] = {"passed": 0, "failed": 0}
        
        # Run test
        passed, details = run_test(local_agent, test_input, expected_tool, expected_device, description)
        
        # Track results
        if passed:
            results["passed"] += 1
            category_results[current_category]["passed"] += 1
            status = "✅"
        else:
            results["failed"] += 1
            category_results[current_category]["failed"] += 1
            status = "❌"
            failed_tests.append((test_input, expected_tool, details, description))
        
        # Print progress
        print(f"\n[{i+1}/{len(TEST_CASES)}] {description}")
        print(f"  Input: \"{test_input}\"")
        print(f"  {details}")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    accuracy = (results["passed"] / results["total"]) * 100
    print(f"\n📊 Overall Accuracy: {results['passed']}/{results['total']} ({accuracy:.1f}%)")
    
    if failed_tests:
        print(f"\n❌ Failed Tests ({len(failed_tests)}):")
        for test_input, expected, details, desc in failed_tests:
            print(f"  • \"{test_input}\" - {desc}")
            print(f"    {details}")
    
    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)
    
    return results


if __name__ == "__main__":
    # Import and initialize LocalAgent
    import sys
    sys.path.insert(0, ".")
    
    from agent.llm_agent.local_agent import LocalAgent
    
    print("\n🚀 Initializing LocalAgent with Qwen 2.5 3B...")
    agent = LocalAgent(model_type="qwen")
    
    if agent.llm is None:
        print("❌ Failed to load model. Tests cannot run.")
        sys.exit(1)
    
    # Run all tests
    results = run_all_tests(agent)
    
    # Exit with appropriate code
    sys.exit(0 if results["failed"] == 0 else 1)
