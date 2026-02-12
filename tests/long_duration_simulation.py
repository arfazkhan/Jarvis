"""
Real-World Stress Simulation (Long Duration)
=============================================
Simulates 15 days of building operation in ~30 minutes (depending on LLM speed).
Objective: Accumulate history to overcome "insufficient data" warnings and verify long-term stability.

Features:
- Closed Loop Physics: Agent actions (e.g., changing setpoints) affect future state.
- Time Acceleration: Mocks datetime to run days in minutes.
- Real Agent Stack: Uses actual UnifiedLLM, MemoryOrchestrator, and Skillbook.
"""

import os
import sys
import time
import json
import asyncio
import logging
import shutil
import random
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from colorama import init, Fore, Style
from dotenv import load_dotenv

# Initialize
init()
load_dotenv()

# Add project root to path
sys.path.append(os.getcwd())

# Import Agent Components
from agent_advisory.goal_generator import GoalDiscoveryEngine
from agent_cognitive.meta_cognition import MetaCognition
from agent_bms.skillbook import BuildingSkillbook
from agent_unified.llm import UnifiedLLM

# Configuration
SIMULATION_DAYS = 15
STEPS_PER_DAY = 2 # Morning and Afternoon checks
TOTAL_STEPS = SIMULATION_DAYS * STEPS_PER_DAY
SPEED_FACTOR = 100 # Not strictly used for sleeps, but conceptual
TEST_DIR = "tests_data/stress_sim"

# Logger Setup
logging.basicConfig(level=logging.WARNING, format='%(message)s') # Reduce noise, rely on custom prints
logger = logging.getLogger("stress_sim")

class ClosedLoopWorld:
    """Simulated Building Physics Model."""
    def __init__(self):
        # State Variables
        self.outdoor_temp = 32.0 # C
        self.indoor_temp = 24.0
        self.chiller_setpoint = 7.0
        self.chiller_efficiency = 0.95 # COP ratio relative to nominal
        self.vibration_level = 1.2 # mm/s (Normal < 4)
        self.occupancy = "medium"
        
        # Hidden variables (faults)
        self.condenser_fouling = 0.0 # 0 to 1.0
        self.wear_tear = 0.0
        
    def step(self, hour: int, agent_actions: list):
        """Evolve the world state by one time step."""
        
        # 1. External Factors (Weather/Occupancy)
        if 8 <= hour <= 18:
            self.outdoor_temp = 35.0 + random.uniform(-1, 2)
            self.occupancy = "high"
        else:
            self.outdoor_temp = 28.0 + random.uniform(-1, 1)
            self.occupancy = "low"
            
        # 2. Process Agent Actions
        for action in agent_actions:
            if "setpoint" in action.lower():
                # Extract number
                try:
                    val = float(''.join(c for c in action if c.isdigit() or c == '.'))
                    self.chiller_setpoint = max(5.0, min(10.0, val))
                except:
                    pass
            
            if "maintenance" in action.lower():
                self.condenser_fouling = 0.0
                self.vibration_level = 1.2
                
        # 3. Physics Evolution
        
        # Cooling Load
        delta_t = self.outdoor_temp - self.indoor_temp
        load = delta_t * 2.5 + (5.0 if self.occupancy == "high" else 1.0)
        
        # Cooling Capacity (affected by Setpoint & Efficiency)
        # Lower setpoint = strictly better cooling, but more energy
        capacity = (12.0 - self.chiller_setpoint) * 5.0 * self.chiller_efficiency
        
        # Indoor Temp changes
        imbalance = load - capacity
        self.indoor_temp += imbalance * 0.1 # Thermal inertia
        self.indoor_temp = max(18.0, min(30.0, self.indoor_temp))
        
        # Degradation
        self.condenser_fouling += 0.015 # Fast degradation for sim
        self.chiller_efficiency = max(0.6, 0.95 - (self.condenser_fouling * 0.5))
        
        # Vibration increases if setpoint changes rapidly or fouling is high
        if self.condenser_fouling > 0.3:
            self.vibration_level += 0.15
            
        return self.get_readings()
        
    def get_readings(self):
        """Return sensor data as dictionary."""
        return {
            "chiller_01_supply_temp": self.chiller_setpoint + random.uniform(-0.2, 0.2),
            "chiller_01_vibration": self.vibration_level + random.uniform(-0.1, 0.1),
            "zone_temp_avg": self.indoor_temp,
            "outdoor_temp": self.outdoor_temp,
            "efficiency_index": self.chiller_efficiency,
            "power_consumption_kw": 450.0 + (35 - self.chiller_setpoint)*10
        }

class TimeTraveler:
    """Manages simulated time."""
    def __init__(self, start_date):
        self.current_time = start_date
        
    def now(self):
        return self.current_time
    
    def advance(self, hours):
        self.current_time += timedelta(hours=hours)
        return self.current_time

async def run_step(world, traveler, memory, brain, llm, step_num):
    """Execute a single simulation step."""
    
    current_time = traveler.now()
    step_desc = f"Day {(step_num // 2) + 1} {'Morning' if current_time.hour < 12 else 'Evening'}"
    print(f"\n{Fore.CYAN}--- [{step_desc}] {current_time.strftime('%Y-%m-%d %H:%M')} ---{Style.RESET_ALL}")
    
    # 1. Physics Step
    sensors = world.step(current_time.hour, []) # TODO: Pass previous actions?
    print(f"{Fore.YELLOW}[World State] Temp: {sensors['zone_temp_avg']:.1f}C | Vib: {sensors['chiller_01_vibration']:.2f} | Eff: {sensors['efficiency_index']:.2f}{Style.RESET_ALL}")
    
    # 2. Store Observation (Memory)
    # The brain normally does this, but we simulate the 'BMS Connector' ingestion here
    obs_text = (
        f"At {current_time.strftime('%H:%M')}, Building Status: "
        f"Zone Temp {sensors['zone_temp_avg']:.1f}C, "
        f"Chiller Vibration {sensors['chiller_01_vibration']:.2f}mm/s, "
        f"Efficiency {sensors['efficiency_index']:.2f}."
    )
    # We cheat and inject directly to ensure history building
    memory.remember(obs_text, "observation", context="bms_log")
    
    # 3. Agent Tick (Cognitive Step)
    # We construct a scenario based on sensors to trigger the agent
    # If vibration is high, we flag it as an issue to prompt action
    scenario_desc = f"Routine Check at {current_time}"
    if sensors["chiller_01_vibration"] > 4.0:
        scenario_desc = "CRITICAL: High Vibration Alarm on Chiller-01"
    elif sensors["zone_temp_avg"] > 26.0:
        scenario_desc = "WARNING: Global High Temperature"
        
    # Run Agent Logic (MetaCognition)
    # We mock the input context to include our simulated sensors
    print(f"[Agent] Analyzing: {scenario_desc}")
    
    # NOTE: In a real 'tick', the agent would query tools. 
    # Here we invoke the reasoning loop.
    # For this simulation, we'll ask the brain to 'reflect' and 'decide' based on the observation.
    
    # Creating a simplified prompt for the agent's decision
    decision_prompt = f"""
    Current Time: {current_time}
    Scenario: {scenario_desc}
    Sensor Data: {json.dumps(sensors)}
    History: {memory.recall(scenario_desc, memory_type="observations", limit=3)}
    
    Task: Analyze the situation. If a fault is detecting, decide on a mitigation action (e.g., adjust setpoint, schedule maintenance).
    If normal, just log 'Monitoring'.
    
    Output JSON: {{ "analysis": string, "action": string, "reasoning": string }}
    """
    
    try:
        # Use the Agent's internal LLM directly to simulate the decision loop
        result = await llm.ask_json([{"role": "user", "content": decision_prompt}])
        
        print(f"{Fore.GREEN}[Decision] Action: {result.get('action')} | Reason: {result.get('reasoning')}{Style.RESET_ALL}")
        
        return result.get('action', 'monitor')
        
    except Exception as e:
        print(f"{Fore.RED}[Error] Agent Failure: {e}{Style.RESET_ALL}")
        return "error"

def main():
    # Cleanup
    if os.path.exists(TEST_DIR):
        try:
            shutil.rmtree(TEST_DIR)
        except:
            pass
            
    print(f"{Fore.MAGENTA}=== ARVIS 15-Day Stress Test ==={Style.RESET_ALL}")
    print("Initializing components...")
    
    # Setup Time Traveler
    start_date = datetime(2026, 6, 1, 9, 0, 0)
    traveler = TimeTraveler(start_date)
    
    world = ClosedLoopWorld()
    
    # Patch DateTime for Components
    real_datetime = datetime
    class MockDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return traveler.now()
            
    p1 = patch('agent.memory.observation_store.datetime', MockDatetime)
    p2 = patch('agent.memory.preference_store.datetime', MockDatetime)
    p3 = patch('agent.memory.orchestrator.datetime', MockDatetime)
    
    with p1, p2, p3:
        # Initialize Agent Components with patched time
        # We need to construct them INSIDE the patch context so they pick up the mock
        from agent.memory.orchestrator import MemoryOrchestrator
        
        memory = MemoryOrchestrator(persist_dir=os.path.join(TEST_DIR, "memories"))
        brain = MetaCognition("stress_test_tower")
        llm = UnifiedLLM()
        
        # Inject memory into brain if architecture allows, or just use it alongside
        # In this simulation, we are orchestrating the loop manually
        
        # Loop
        for step in range(TOTAL_STEPS):
            # Run async step
            action = asyncio.run(run_step(world, traveler, memory, brain, llm, step))
            
            # Apply Action to World (for next step)
            # We assume the action takes effect immediately or over the 12 hour jump
            world.step(traveler.now().hour, [action])
            
            # Advance Time (12 hours)
            traveler.advance(12)
            
            # Optional: Sleep to allow user to read output (or remove for max speed)
            # time.sleep(0.5) 
            
    print(f"\n{Fore.MAGENTA}=== Simulation Complete ==={Style.RESET_ALL}")

if __name__ == "__main__":
    main()
