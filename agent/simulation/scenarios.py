import time
import threading
import json
import os
import datetime
import random
from groq import Groq

class SimulationEngine:
    def __init__(self, event_bus, device_controller, state_engine):
        self.event_bus = event_bus
        self.device = device_controller
        self.state_engine = state_engine
        self.running = False
        
        # Initialize Groq client for AI-powered scenario generation
        api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=api_key) if api_key else None

    def generate_realistic_day(self, day_number, day_of_week, persona_type="working_professional", month=11):
        """
        Use LLM to generate a realistic day's worth of events.
        Returns a list of events with timestamps (relative to day start).
        """
        if not self.client:
            return None
        
        # Determine season and characteristics
        if month in [12, 1, 2]:
            season = "winter"
            daylight_start = 7.5  # Late sunrise
            daylight_end = 17.0   # Early sunset
            temp_desc = "cold, heating needed"
        elif month in [3, 4, 5]:
            season = "spring"
            daylight_start = 6.5
            daylight_end = 19.0
            temp_desc = "mild, pleasant"
        elif month in [6, 7, 8]:
            season = "summer"
            daylight_start = 5.5  # Early sunrise
            daylight_end = 20.5   # Late sunset
            temp_desc = "hot, cooling needed"
        else:
            season = "autumn"
            daylight_start = 7.0
            daylight_end = 18.0
            temp_desc = "cool, layers needed"
            
        prompt = f"""You are simulating realistic smart home behavior for training data.

PERSONA: {persona_type}
DAY: Day #{day_number} of 30, {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day_of_week]}
SEASON: {season.upper()} (Month: {month})
WEATHER: {temp_desc}
DAYLIGHT: Sunrise ~{daylight_start:.1f}:00, Sunset ~{daylight_end:.1f}:00

DEVICES AVAILABLE:
- switch_1, endpoint 1: Bedroom light (on/off)
- switch_1, endpoint 2: Living room light (on/off)  
- switch_1, endpoint 3: Kitchen light (on/off)
- Motion sensors in: bedroom, kitchen, living_room, bathroom

PERSONA PROFILES:
- working_professional: Weekday 9-5 job, leaves house 7:30 AM, returns 6 PM
- work_from_home: Home all day, frequent room changes, lunch break patterns
- retiree: Wakes early, stays home, afternoon activities, early bedtime
- student: Irregular schedule, late nights, mid-morning wake, study patterns
- family_with_kids: Multiple wake times, dinner rush, bedtime routines for kids
- shift_worker: Varied sleep schedule, may sleep during day

YOUR TASK:
Generate ONE realistic day of smart home activity. Consider:

1. SEASONAL BEHAVIOR:
   - {season}: {temp_desc}, daylight {daylight_start}-{daylight_end}
   - More lighting needed when dark (winter mornings, summer late evenings)
   - Energy usage patterns (heating/cooling affects behavior)
   - Seasonal activities (winter = more indoor time, summer = outdoor activities)

2. NATURAL VARIATIONS: Don't use exact same times - vary by 5-30 minutes
3. REALISTIC SEQUENCES: Motion before lights, logical room transitions
4. LIFE EVENTS: Maybe they're sick (stay home), have guests, working late, on vacation
5. ENERGY AWARENESS: Sometimes forget lights, sometimes manually save energy
6. WEATHER IMPACT: Rainy day = stay indoors more, sunny = maybe leave earlier
7. MOOD/ENERGY: Tired day = less activity, energetic = more room usage
8. FORGOTTEN ROUTINES: Occasionally forget to turn off lights, unusual bathroom trips
9. MULTI-TASKING: Kitchen + living room lights on simultaneously during meal prep
10. WEEKEND VS WEEKDAY: Dramatically different patterns
11. REALISTIC ANOMALIES: Midnight snack, early wake-up, power nap, guest over

OUTPUT FORMAT (JSON):
{{
  "day_summary": "Brief description of this day's pattern",
  "special_events": ["sick day", "guest over", "working late"] or [],
  "events": [
    {{"time_hour": 6.5, "type": "presence_update", "location": "bedroom", "value": "detected"}},
    {{"time_hour": 6.52, "device": "switch_1", "endpoint": 1, "state": "on"}},
    ...
  ]
}}

RULES:
- time_hour is decimal hours from midnight (6.5 = 6:30 AM, 18.75 = 6:45 PM)
- Include 8-20 events per day (don't over-generate)
- Make it FEEL human - imperfect, varied, realistic
- Include at least one interesting variation or anomaly
- Consider the day of week, season, and daylight hours
- Adapt lighting patterns to sunrise/sunset times
- Some days should be boring/routine, others interesting

Generate events for this SPECIFIC day now:"""

        try:
            response = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": "You are a smart home behavior simulator. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,  # High creativity for varied scenarios
                max_tokens=1500
            )
            
            # Parse the LLM response
            content = response.choices[0].message.content
            # Extract JSON from markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
                
            scenario = json.loads(content.strip())
            return scenario
            
        except Exception as e:
            print(f"[Simulation] LLM generation error: {e}")
            return None

    def _generate_fallback_day(self, day_start, day_of_week):
        """Fallback to simple pattern if LLM fails."""
        is_weekend = day_of_week >= 5
        wake_time = day_start + (8 * 3600) if is_weekend else day_start + (6.5 * 3600)
        
        # Simple morning routine
        self.event_bus.publish({
            "type": "presence_update",
            "payload": {"location": "bedroom", "value": "detected"},
            "timestamp": wake_time,
            "source": "simulation_fallback"
        })
        self.event_bus.publish({
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
            "timestamp": wake_time + 5,
            "source": "simulation_fallback"
        })
        
        # Evening
        bedtime = day_start + (22 * 3600)
        self.event_bus.publish({
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 1, "state": "off"},
            "timestamp": bedtime,
            "source": "simulation_fallback"
        })

    def generate_history(self, days=30):
        """
        Generate rich, AI-powered realistic history.
        Uses LLM to create varied daily scenarios.
        """
        print(f"[Simulation] Generating {days} days of AI-powered realistic history...")
        self.state_engine.state["history"] = []
        
        now = time.time()
        seconds_per_day = 86400
        
        # Randomly choose persona types for variety
        personas = ["working_professional", "work_from_home", "retiree", "student", "family_with_kids"]
        chosen_persona = random.choice(personas)
        print(f"[Simulation] Using persona: {chosen_persona}")
        
        for day_offset in range(days, 0, -1):
            day_timestamp = now - (day_offset * seconds_per_day)
            day_of_week = datetime.datetime.fromtimestamp(day_timestamp).weekday()
            day_start = now - (day_offset * seconds_per_day)
            current_month = datetime.datetime.fromtimestamp(day_timestamp).month
            
            # Occasionally switch persona (life change, vacation, etc.)
            if random.random() < 0.1:
                chosen_persona = random.choice(personas)
            
            # Try to generate with LLM
            scenario = self.generate_realistic_day(
                day_number=days - day_offset + 1,
                day_of_week=day_of_week,
                persona_type=chosen_persona,
                month=current_month
            )
            
            if scenario and "events" in scenario:
                # Convert LLM-generated events to actual events
                print(f"[Simulation] Day {days - day_offset + 1}: {scenario.get('day_summary', 'Generated')}")
                
                for event in scenario["events"]:
                    timestamp = day_start + (event["time_hour"] * 3600)
                    
                    if "location" in event:
                        # Motion/presence event
                        self.event_bus.publish({
                            "type": event.get("type", "presence_update"),
                            "payload": {
                                "location": event["location"],
                                "value": event.get("value", "detected")
                            },
                            "timestamp": timestamp,
                            "source": "simulation_ai"
                        })
                    elif "device" in event:
                        # Device control event
                        self.event_bus.publish({
                            "type": "relay_toggled",
                            "payload": {
                                "device": event["device"],
                                "endpoint": event["endpoint"],
                                "state": event["state"]
                            },
                            "timestamp": timestamp,
                            "source": "simulation_ai"
                        })
            else:
                # Fallback to basic pattern if LLM fails
                print(f"[Simulation] Day {days - day_offset + 1}: Using fallback pattern")
                self._generate_fallback_day(day_start, day_of_week)
        
        print(f"[Simulation] History generation complete with {days} days of AI-powered data.")

    def run_scenario(self, name):
        if name == "morning":
            threading.Thread(target=self._scenario_morning).start()
        elif name == "leaving":
            threading.Thread(target=self._scenario_leaving).start()
        elif name == "evening":
            threading.Thread(target=self._scenario_evening).start()
        else:
            print(f"[Simulation] Unknown scenario: {name}")

    # ------------------------------------------------------------------ #
    # Pre-defined Scenarios (for manual testing)
    # ------------------------------------------------------------------ #
    def _scenario_morning(self):
        print("[Simulation] Starting Morning Routine...")
        self.event_bus.publish({
            "type": "time_update",
            "payload": {"time_of_day": "morning", "hour": 7},
            "timestamp": time.time()
        })
        print("[Simulation] Time is now 07:00")
        time.sleep(2)
        
        # Turn on bedroom light (relay 1)
        self.device.control_relay(1, "on")
        time.sleep(2)
        
        # Turn on kitchen light (relay 3)
        self.device.control_relay(3, "on")
        print("[Simulation] Morning Routine Complete")

    def _scenario_leaving(self):
        print("[Simulation] Starting Leaving Routine...")
        self.event_bus.publish({
            "type": "time_update",
            "payload": {"time_of_day": "morning", "hour": 8, "minute": 30},
            "timestamp": time.time()
        })
        print("[Simulation] Time is now 08:30")
        time.sleep(1)
        
        # Turn off bedroom light
        self.device.control_relay(1, "off")
        time.sleep(1)
        
        # Turn off kitchen light
        self.device.control_relay(3, "off")
        print("[Simulation] Leaving Routine Complete")

    def _scenario_evening(self):
        print("[Simulation] Starting Evening Routine...")
        self.event_bus.publish({
            "type": "time_update",
            "payload": {"time_of_day": "evening", "hour": 18},
            "timestamp": time.time()
        })
        print("[Simulation] Time is now 18:00")
        time.sleep(2)
        
        # Turn on living room light (relay 2)
        self.device.control_relay(2, "on")
        time.sleep(3)
        
        # Time passes...
        self.event_bus.publish({
            "type": "time_update",
            "payload": {"time_of_day": "night", "hour": 23},
            "timestamp": time.time()
        })
        print("[Simulation] Time is now 23:00")
        time.sleep(1)
        
        # Turn off living room light
        self.device.control_relay(2, "off")
        print("[Simulation] Evening Routine Complete")
