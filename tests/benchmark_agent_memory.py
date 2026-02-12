"""
Long-Term Memory Benchmark
==========================
Simulates 30 days of agent operation to verify:
1. Memory Persistence: Do preferences stay?
2. Memory Decay: Do old observations expire?
3. Performance: Does retrieval slow down as DB grows?
4. Retrieval Accuracy: Can we recall Day 1 info on Day 30?
"""

import os
import sys
import shutil
import time
import gc
import random
import logging
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from colorama import init, Fore, Style

# Ensure environment is set up
sys.path.append(os.getcwd())
init()

# Imports specifically for patching
import agent.memory.observation_store
import agent.memory.preference_store
import agent.memory.orchestrator

from agent.memory.orchestrator import MemoryOrchestrator
# We define a simple mock simulator to avoid full LLM costs for this benchmark logic
# unless we strictly need the LLM content. For benchmarking memory I/O, randomized text is sufficient 
# and faster/cheaper. 

# Configure Logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("benchmark_memory")
logger.setLevel(logging.INFO)

TEST_DIR = "tests_data/memory_benchmark"

def print_header(title):
    print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}")

def generate_daily_scenario(day_index):
    """Generate deterministic random scenario data."""
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = days_of_week[day_index % 7]
    
    tech_issues = [
        "Chiller efficiency dropped to 65%",
        "AHU-01 vibration warning",
        "VAV-12 stuck damper",
        "CO2 levels slightly elevated in Zone 3",
        "Network latency spike in Building B"
    ]
    
    issue = tech_issues[day_index % len(tech_issues)]
    
    return {
        "day": day_name,
        "observation": f"Observed {issue} on {day_name} morning.",
        "preference_trigger": day_index == 0, # Only set preference on Day 0
        "recall_query": "What happens on " + day_name + "?"
    }

class TimeTraveler:
    """Helper to mock datetime.now() across modules."""
    def __init__(self, start_time):
        self.current_time = start_time
        
    def now(self):
        return self.current_time
    
    def advance_days(self, days):
        self.current_time += timedelta(days=days)
        return self.current_time

def run_benchmark():
    print_header("Initializing 30-Day Memory Benchmark")
    
    # Cleanup previous run
    if os.path.exists(TEST_DIR):
        try:
            shutil.rmtree(TEST_DIR)
        except:
            pass
            
    # Initialize Memory
    # Note: We don't patch init, only the usage of datetime
    memory = MemoryOrchestrator(persist_dir=TEST_DIR, observation_decay_days=7)
    print(f"{Fore.GREEN}✓ Memory System Initialized at {TEST_DIR}{Style.RESET_ALL}")
    print(f"  > Observation Decay set to 7 days")
    
    start_time = datetime(2026, 1, 1, 8, 0, 0) # Jan 1st 2026
    traveler = TimeTraveler(start_time)
    
    metrics = {
        "total_obs_stored": 0,
        "total_prefs_stored": 0,
        "retrieval_times": [],
        "decay_checks": []
    }
    
    print_header("Starting Simulation Loop (30 Days)")
    
    # We need to patch datetime in the specific modules where it is used
    # This mock must match the signature of datetime class methods used (now, fromisoformat, etc)
    # This is complex in Python. A simpler way for this benchmark is to rely on the functional correctness
    # of the TimeTraveler if we could inject it, but the classes import datetime directly.
    # We will use unittest.mock.patch to replace the 'datetime' CLASS in those modules.
    
    # Create a Mock Datetime Class that proxies to real datetime but overrides now()
    real_datetime = datetime
    class MockDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return traveler.now()

    # Apply patches
    p1 = patch('agent.memory.observation_store.datetime', MockDatetime)
    p2 = patch('agent.memory.preference_store.datetime', MockDatetime)
    p3 = patch('agent.memory.orchestrator.datetime', MockDatetime)
    
    with p1, p2, p3:
        for day in range(30):
            current_date = traveler.now()
            print(f"\rSimulation Day {day+1}: {current_date.strftime('%Y-%m-%d')}...", end="")
            
            scenario = generate_daily_scenario(day)
            
            # 1. Day 0: Set Long-Term Preference
            if scenario["preference_trigger"]:
                memory.remember(
                    content="Operator prefers notifications via Email for critical alarms",
                    memory_type="preference",
                    key="alert_pref",
                    context="alerts",
                    importance=1.0
                )
                metrics["total_prefs_stored"] += 1
                
            # 2. Daily Observation (Short-Term)
            memory.remember(
                content=scenario["observation"],
                memory_type="observation",
                context="daily_log",
                importance=0.5 # Should decay after ~7 days * 1.0 = 7 days? Or decay logic: 7 * (0.5+imp)?
                # logic: decay_days * (0.5 + importance) = 7 * (0.5+0.5) = 7 days.
            )
            metrics["total_obs_stored"] += 1
            
            # 3. Retrieval Performance Test
            t0 = time.time()
            # Search for the preference set on Day 0
            res = memory.recall("how to send critical alarms", memory_type="preferences")
            latency = (time.time() - t0) * 1000 # ms
            metrics["retrieval_times"].append(latency)
            
            # 4. Verify Decay (Every 10 days)
            if (day + 1) % 10 == 0:
                print(f"\n  [Day {day+1}] Running Cleanup & Audit...")
                # Run cleanup (which uses the mocked 'now' to find expired items)
                memory.cleanup()
                
                # Check stats
                stats = memory.get_stats()
                obs_count = stats["observations_count"]
                metrics["decay_checks"].append(obs_count)
                print(f"  > Active Observations: {obs_count}")
                # We expect roughly 7-10 active observations if decay is working
                
            # Advancement
            traveler.advance_days(1)
            
    print("\n" + Fore.GREEN + "✓ Simulation Complete" + Style.RESET_ALL)
    
    # --- Final Report ---
    print_header("Benchmark Results")
    
    avg_latency = sum(metrics["retrieval_times"]) / len(metrics["retrieval_times"])
    stats = memory.get_stats()
    
    print(f"Total Simulated Days: 30")
    print(f"Total Observations Written: {metrics['total_obs_stored']}")
    print(f"Final Identity (Preference) Count: {stats['preferences_count']} (Expected: 1)")
    print(f"Final Active Observations: {stats['observations_count']} (Expected ~7-10 due to decay)")
    print(f"Average Retrieval Latency: {avg_latency:.2f} ms")
    
    # Validations
    success = True
    
    # 1. Persistence Check
    # Verify the Day 0 preference is still recallable on Day 30
    final_recall = memory.recall("alert preference", memory_type="preferences")
    if getattr(final_recall, 'features', None) is None and len(final_recall) > 0 and "Email" in final_recall[0]['content']:
        print(f"{Fore.GREEN}✓ Long-Term Memory (Day 0) persisted to Day 30{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}✗ Long-Term Memory lost! Retrieved: {final_recall}{Style.RESET_ALL}")
        success = False
        
    # 2. Decay Check
    # We generated 30 observations. Decay is 7 days. We should have ~7-8 left.
    # Definitely < 30.
    if stats['observations_count'] < 20:
        print(f"{Fore.GREEN}✓ Memory Decay Functional (Count {stats['observations_count']} < 30){Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}✗ Memory Decay Failed (Count {stats['observations_count']} implies no cleanup){Style.RESET_ALL}")
        success = False
            
    # Cleanup
    try:
        del memory
        gc.collect()
        shutil.rmtree(TEST_DIR)
        print(f"\n[Cleanup] Removed {TEST_DIR}")
    except:
        pass
        
    return success

if __name__ == "__main__":
    if run_benchmark():
        sys.exit(0)
    else:
        sys.exit(1)
