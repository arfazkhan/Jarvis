"""
LocalAgent Pattern Learning Test
Simulates real user interactions over time to test memory and pattern detection.
"""

import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Simulated time progression
class SimulatedClock:
    def __init__(self, start_time: str = "2026-01-10 07:00"):
        self.current = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    
    def advance(self, minutes: int = 0, hours: int = 0, days: int = 0):
        self.current += timedelta(minutes=minutes, hours=hours, days=days)
    
    def time_of_day(self) -> str:
        hour = self.current.hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"
    
    def __str__(self):
        return self.current.strftime("%Y-%m-%d %H:%M")


# Memory store (simulates persistent storage)
class MemoryStore:
    def __init__(self):
        self.patterns: Dict[str, Any] = {}
        self.command_history: List[Dict] = []
    
    def log(self, key: str, value: str, timestamp: str):
        self.patterns[key] = {"value": value, "timestamp": timestamp, "count": 1}
        print(f"[Memory] 📝 Stored: {key} = {value}")
    
    def recall(self, query: str) -> List[Dict]:
        matches = []
        for key, data in self.patterns.items():
            if query.lower() in key.lower() or query.lower() in str(data["value"]).lower():
                matches.append({"key": key, **data})
        return matches
    
    def add_command(self, command: str, tool: str, device: str, time_of_day: str):
        self.command_history.append({
            "command": command,
            "tool": tool,
            "device": device,
            "time_of_day": time_of_day
        })
    
    def detect_patterns(self) -> List[str]:
        """Analyze command history to detect patterns."""
        patterns = []
        
        # Count device usage by time of day
        time_device_counts = {}
        for cmd in self.command_history:
            key = f"{cmd['time_of_day']}:{cmd['device']}"
            time_device_counts[key] = time_device_counts.get(key, 0) + 1
        
        # Find patterns (used 3+ times at same time of day)
        for key, count in time_device_counts.items():
            if count >= 3:
                time_of_day, device = key.split(":")
                patterns.append(f"User often uses '{device}' in the {time_of_day}")
        
        return patterns


# Tool schema for LocalAgent
TOOLS_SCHEMA = [
    {"name": "turn_on", "description": "Turn on a device"},
    {"name": "turn_off", "description": "Turn off a device"},
    {"name": "log_memory", "description": "Store a learned pattern or preference"},
    {"name": "escalate", "description": "Escalate to cloud LLM"},
]

KNOWN_DEVICES = [
    "kitchen light", "bedroom light", "living room light",
    "bathroom light", "porch light", "ac", "fan", "tv"
]


# Simulated user behavior over a week
SIMULATED_WEEK = [
    # Day 1 - Monday Morning
    {"time": "07:00", "command": "turn on kitchen light", "expected": "turn_on"},
    {"time": "07:30", "command": "turn on bathroom light", "expected": "turn_on"},
    {"time": "08:00", "command": "turn off kitchen light", "expected": "turn_off"},
    {"time": "18:00", "command": "turn on living room light", "expected": "turn_on"},
    {"time": "22:00", "command": "turn off living room light", "expected": "turn_off"},
    {"time": "22:05", "command": "turn on bedroom light", "expected": "turn_on"},
    {"time": "23:00", "command": "turn off bedroom light", "expected": "turn_off"},
    
    # Day 2 - Tuesday (similar pattern)
    {"time": "+1d 07:00", "command": "turn on kitchen light", "expected": "turn_on"},
    {"time": "+0 07:15", "command": "remember I always use kitchen light first thing", "expected": "log_memory"},
    {"time": "+0 18:00", "command": "turn on living room light", "expected": "turn_on"},
    {"time": "+0 22:00", "command": "turn on bedroom light", "expected": "turn_on"},
    
    # Day 3 - Wednesday (pattern continues)
    {"time": "+1d 07:00", "command": "kitchen light on", "expected": "turn_on"},
    {"time": "+0 18:30", "command": "living room light on", "expected": "turn_on"},
    {"time": "+0 22:00", "command": "bedroom light", "expected": "turn_on"},
    
    # Day 4 - Thursday
    {"time": "+1d 07:00", "command": "yo turn on the kitchen light", "expected": "turn_on"},
    {"time": "+0 18:00", "command": "turn on living room light", "expected": "turn_on"},
    
    # Day 5 - Friday
    {"time": "+1d 07:00", "command": "kitchen light please", "expected": "turn_on"},
    {"time": "+0 19:00", "command": "I prefer dim lights in the evening", "expected": "log_memory"},
    
    # Day 6 - Saturday (different pattern - later wake up)
    {"time": "+1d 09:00", "command": "turn on kitchen light", "expected": "turn_on"},
    {"time": "+0 10:00", "command": "its the weekend I like to sleep in", "expected": "log_memory"},
    
    # Day 7 - Sunday
    {"time": "+1d 09:30", "command": "kitchen light on", "expected": "turn_on"},
    {"time": "+0 20:00", "command": "movie time", "expected": "escalate"},  # Complex - escalate
]


def parse_time(time_str: str, clock: SimulatedClock):
    """Parse relative time strings like '+1d 07:00' or '07:00'."""
    if time_str.startswith("+"):
        parts = time_str.split(" ")
        delta = parts[0]
        new_time = parts[1] if len(parts) > 1 else None
        
        if "d" in delta:
            days = int(delta.replace("+", "").replace("d", ""))
            clock.advance(days=days)
        
        if new_time:
            clock.current = clock.current.replace(
                hour=int(new_time.split(":")[0]),
                minute=int(new_time.split(":")[1])
            )
    else:
        clock.current = clock.current.replace(
            hour=int(time_str.split(":")[0]),
            minute=int(time_str.split(":")[1])
        )


def run_simulation(local_agent):
    """Run the full week simulation."""
    print("\n" + "="*70)
    print("LOCALAGENT PATTERN LEARNING SIMULATION")
    print("="*70)
    
    clock = SimulatedClock("2026-01-10 06:00")
    memory = MemoryStore()
    
    results = {"passed": 0, "failed": 0, "total": len(SIMULATED_WEEK)}
    
    for i, scenario in enumerate(SIMULATED_WEEK):
        # Advance simulated time
        parse_time(scenario["time"], clock)
        time_of_day = clock.time_of_day()
        
        print(f"\n[{clock}] ({time_of_day.upper()})")
        print(f"  User: \"{scenario['command']}\"")
        
        # Build learned patterns string for prompt
        detected = memory.detect_patterns()
        learned_str = "\n".join([f"• {p}" for p in detected[:3]]) if detected else ""
        
        # Call LocalAgent
        try:
            result = local_agent.generate_tool_call(
                user_input=scenario["command"],
                tools_schema=TOOLS_SCHEMA,
                known_devices=KNOWN_DEVICES,
                learned_patterns=f"[Detected Patterns]\n{learned_str}" if learned_str else ""
            )
            
            if result is None:
                actual_tool = "escalate"
                device = ""
            else:
                actual_tool = result[0].get("tool", "unknown")
                args = result[0].get("args", {})
                device = args.get("device_id", "")
            
            # Check result
            expected = scenario["expected"]
            passed = actual_tool == expected
            
            if passed:
                results["passed"] += 1
                print(f"  ✅ {actual_tool}({device if device else 'N/A'})")
                
                # Track for pattern detection
                if actual_tool in ("turn_on", "turn_off") and device:
                    memory.add_command(scenario["command"], actual_tool, device, time_of_day)
                
                # Handle log_memory
                if actual_tool == "log_memory":
                    key = args.get("key", "unknown")
                    value = args.get("value", "")
                    memory.log(key, value, str(clock))
            else:
                results["failed"] += 1
                print(f"  ❌ Got {actual_tool}, expected {expected}")
                
        except Exception as e:
            results["failed"] += 1
            print(f"  💥 Error: {e}")
    
    # Final pattern analysis
    print("\n" + "="*70)
    print("PATTERN ANALYSIS")
    print("="*70)
    
    detected_patterns = memory.detect_patterns()
    if detected_patterns:
        print("\n🔍 Detected Behavioral Patterns:")
        for pattern in detected_patterns:
            print(f"  • {pattern}")
    
    if memory.patterns:
        print("\n📝 Stored Memories:")
        for key, data in memory.patterns.items():
            print(f"  • {key}: {data['value']}")
    
    # Summary
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    accuracy = (results["passed"] / results["total"]) * 100
    print(f"\n📊 Accuracy: {results['passed']}/{results['total']} ({accuracy:.1f}%)")
    print(f"📅 Simulated: 7 days of user interactions")
    print(f"🧠 Patterns detected: {len(detected_patterns)}")
    print(f"💾 Memories stored: {len(memory.patterns)}")
    
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    
    from agent_home.llm_agent.local_agent import LocalAgent
    
    print("\n🚀 Loading Qwen 2.5 3B for pattern learning test...")
    agent = LocalAgent(model_type="qwen")
    
    if agent.llm is None:
        print("❌ Model failed to load")
        sys.exit(1)
    
    results = run_simulation(agent)
    sys.exit(0 if results["failed"] == 0 else 1)
