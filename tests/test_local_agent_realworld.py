"""
LocalAgent REAL-WORLD Battle Test
Natural language test cases simulating how actual home users speak.
Includes typos, casual speech, incomplete sentences, accents, etc.
"""

import json
import time
from typing import List, Dict, Tuple

# Real-world test cases: (input, expected_tool, expected_device, description)
REAL_WORLD_TESTS = [
    # ═══════════════════════════════════════════════════════════
    # CASUAL SPEECH - How people actually talk
    # ═══════════════════════════════════════════════════════════
    ("yo turn on the kitchen light", "turn_on", "kitchen", "Casual 'yo' prefix"),
    ("hey get the bedroom light on", "turn_on", "bedroom", "Casual 'hey get'"),
    ("just turn off the bathroom light", "turn_off", "bathroom", "With 'just'"),
    ("go ahead and turn on porch light", "turn_on", "porch", "With 'go ahead and'"),
    ("can ya turn off the kitchen light", "turn_off", "kitchen", "Casual 'ya'"),
    ("lemme get that bedroom light off", "turn_off", "bedroom", "Casual 'lemme get'"),
    ("hit the kitchen light", "turn_on", "kitchen", "Slang 'hit the light'"),
    ("kill the bedroom light", "turn_off", "bedroom", "Slang 'kill the light'"),
    
    # ═══════════════════════════════════════════════════════════
    # TYPOS & MISSPELLINGS - Voice transcription errors
    # ═══════════════════════════════════════════════════════════
    ("turn on teh kitchen light", "turn_on", "kitchen", "Typo 'teh'"),
    ("turn of the bedroom light", "turn_off", "bedroom", "Typo 'of' vs 'off'"),
    ("tur on the living room light", "turn_on", "living", "Missing 'n'"),
    ("turn on kichen light", "turn_on", "kitchen", "Typo 'kichen'"),
    ("turn off bedrrom light", "turn_off", "bedroom", "Typo 'bedrrom'"),
    
    # ═══════════════════════════════════════════════════════════
    # INCOMPLETE/LAZY SENTENCES
    # ═══════════════════════════════════════════════════════════
    ("kitchen light", "turn_on", "kitchen", "Just device name - assume on"),
    ("bedroom light please", "turn_on", "bedroom", "Device + please"),
    ("porch light off", "turn_off", "porch", "Device + off"),
    ("ac on", "turn_on", "ac", "Minimal command"),
    ("fan off", "turn_off", "fan", "Minimal command"),
    
    # ═══════════════════════════════════════════════════════════
    # ROOM-BASED REQUESTS (should escalate - no specific device)
    # ═══════════════════════════════════════════════════════════
    ("turn on the kitchen", "escalate", None, "Room only, not device"),
    ("light up the bedroom", "escalate", None, "Vague 'light up'"),
    ("brighten the living room", "escalate", None, "Brightness request"),
    ("make the bathroom brighter", "escalate", None, "Relative brightness"),
    
    # ═══════════════════════════════════════════════════════════
    # CONTEXTUAL/LAZY (should escalate - ambiguous)
    # ═══════════════════════════════════════════════════════════
    ("it's dark in here", "escalate", None, "Implicit request"),
    ("i can't see anything", "escalate", None, "Implicit request"),
    ("too bright", "escalate", None, "Relative complaint"),
    ("need some light", "escalate", None, "Vague request"),
    ("its getting dark", "escalate", None, "Observation, not command"),
    ("lights", "escalate", None, "Just 'lights'"),
    ("light", "escalate", None, "Just 'light'"),
    
    # ═══════════════════════════════════════════════════════════
    # CONVERSATIONAL STARTERS (should escalate)
    # ═══════════════════════════════════════════════════════════
    ("hey arvis", "escalate", None, "Just greeting"),
    ("arvis", "escalate", None, "Just wake word"),
    ("um turn on uh the lights", "escalate", None, "Hesitation + ambiguous"),
    ("so like can you turn on the thing", "escalate", None, "Vague 'the thing'"),
    
    # ═══════════════════════════════════════════════════════════
    # MULTI-STEP/COMPLEX (should escalate)
    # ═══════════════════════════════════════════════════════════
    ("turn on kitchen and bedroom", "escalate", None, "Two devices"),
    ("everything off", "escalate", None, "Multi-device"),
    ("all lights off", "escalate", None, "Multi-device"),
    ("shut it all down", "escalate", None, "Vague multi-device"),
    ("movie time", "escalate", None, "Scene request"),
    ("bedtime", "escalate", None, "Routine request"),
    ("good night mode", "escalate", None, "Mode request"),
    ("i'm going to bed", "escalate", None, "Implicit routine"),
    ("wake me up at 7", "escalate", None, "Alarm request"),
    
    # ═══════════════════════════════════════════════════════════
    # QUESTIONS (should escalate)
    # ═══════════════════════════════════════════════════════════
    ("is the kitchen light on", "escalate", None, "Status question"),
    ("whats on right now", "escalate", None, "Status question"),
    ("did you turn off the bedroom", "escalate", None, "Confirmation question"),
    ("are the lights on", "escalate", None, "Status question"),
    ("hows the ac doing", "escalate", None, "Status question"),
    
    # ═══════════════════════════════════════════════════════════
    # FILLER WORDS & NATURAL SPEECH
    # ═══════════════════════════════════════════════════════════
    ("uh yeah turn on the kitchen light", "turn_on", "kitchen", "Filler 'uh yeah'"),
    ("okay so turn off the bedroom light", "turn_off", "bedroom", "Filler 'okay so'"),
    ("alright turn on the porch light", "turn_on", "porch", "Filler 'alright'"),
    ("you know what turn off the tv", "turn_off", "tv", "Filler 'you know what'"),
    ("actually turn on the fan", "turn_on", "fan", "Correction 'actually'"),
    
    # ═══════════════════════════════════════════════════════════
    # NEGATIVE/CANCEL COMMANDS
    # ═══════════════════════════════════════════════════════════
    ("nevermind", "escalate", None, "Cancel"),
    ("forget it", "escalate", None, "Cancel"),
    ("wait no", "escalate", None, "Cancel"),
    ("stop", "escalate", None, "Stop command"),
    ("cancel that", "escalate", None, "Cancel"),
    
    # ═══════════════════════════════════════════════════════════
    # ACCENT/PRONUNCIATION VARIATIONS (voice transcription)
    # ═══════════════════════════════════════════════════════════
    ("turn on dee kitchen light", "turn_on", "kitchen", "Accent 'dee'"),
    ("switch on the kitchen light", "turn_on", "kitchen", "'switch on' synonym"),
    ("put on the bedroom light", "turn_on", "bedroom", "'put on' synonym"),
    ("shut off the bathroom light", "turn_off", "bathroom", "'shut off' synonym"),
    ("cut the kitchen light", "turn_off", "kitchen", "'cut the light' = off"),
    ("flip the porch light on", "turn_on", "porch", "'flip on'"),
    
    # ═══════════════════════════════════════════════════════════
    # EMOTIONAL/URGENT
    # ═══════════════════════════════════════════════════════════
    ("turn on the damn kitchen light", "turn_on", "kitchen", "Frustrated"),
    ("just turn off the stupid bedroom light", "turn_off", "bedroom", "Annoyed"),
    ("TURN ON THE KITCHEN LIGHT", "turn_on", "kitchen", "Shouting (caps)"),
    ("kitchen light NOW", "turn_on", "kitchen", "Urgent"),
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
    {"name": "log_memory", "description": "Store a learned pattern or preference for future use"},
    {"name": "escalate", "description": "Escalate to cloud LLM"},
]


def run_test(local_agent, test_input: str, expected_tool: str, 
             expected_device: str, description: str) -> Tuple[bool, str, float]:
    """Run a single test case. Returns (passed, details, latency_ms)"""
    start = time.time()
    try:
        result = local_agent.generate_tool_call(
            user_input=test_input,
            tools_schema=TOOLS_SCHEMA,
            known_devices=KNOWN_DEVICES
        )
        latency = (time.time() - start) * 1000
        
        if result is None:
            if expected_tool == "escalate":
                return True, "✅ Correctly escalated (None)", latency
            return False, f"❌ Got None, expected {expected_tool}", latency
        
        actual_tool = result[0].get("tool", "unknown") if result else "none"
        actual_device = result[0].get("args", {}).get("device_id", "") if result else ""
        
        tool_match = actual_tool == expected_tool
        device_match = True
        if expected_device and expected_tool != "escalate":
            device_match = expected_device.lower() in actual_device.lower()
        
        if tool_match and device_match:
            return True, f"✅ {actual_tool}({actual_device})", latency
        elif tool_match and not device_match:
            return False, f"⚠️ Tool OK, wrong device: '{actual_device}'", latency
        else:
            return False, f"❌ Got {actual_tool}, expected {expected_tool}", latency
            
    except Exception as e:
        return False, f"💥 Error: {e}", 0


def run_all_tests(local_agent):
    """Run all tests and report."""
    print("\n" + "="*70)
    print("REAL-WORLD BATTLE TEST - Natural Language Accuracy")
    print("="*70)
    
    results = {"passed": 0, "failed": 0, "total": len(REAL_WORLD_TESTS)}
    failed_tests = []
    latencies = []
    
    for i, (test_input, expected_tool, expected_device, desc) in enumerate(REAL_WORLD_TESTS):
        passed, details, latency = run_test(local_agent, test_input, expected_tool, expected_device, desc)
        latencies.append(latency)
        
        if passed:
            results["passed"] += 1
            print(f"✅ [{i+1}] \"{test_input[:40]}...\" → {details}")
        else:
            results["failed"] += 1
            failed_tests.append((test_input, expected_tool, details, desc))
            print(f"❌ [{i+1}] \"{test_input[:40]}...\" → {details}")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    accuracy = (results["passed"] / results["total"]) * 100
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    
    print(f"\n📊 Accuracy: {results['passed']}/{results['total']} ({accuracy:.1f}%)")
    print(f"⏱️  Avg Latency: {avg_latency:.0f}ms per call")
    
    if failed_tests:
        print(f"\n❌ FAILURES ({len(failed_tests)}):")
        for inp, exp, details, desc in failed_tests:
            print(f"  • [{desc}] \"{inp}\"")
            print(f"    Expected: {exp} | {details}")
    
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    
    from agent_home.llm_agent.local_agent import LocalAgent
    
    print("\n🚀 Loading Qwen 2.5 3B for real-world testing...")
    agent = LocalAgent(model_type="qwen")
    
    if agent.llm is None:
        print("❌ Model failed to load")
        sys.exit(1)
    
    results = run_all_tests(agent)
    sys.exit(0 if results["failed"] == 0 else 1)
