"""
Time-based Scheduler for Automation Engine

Handles cron-like schedules for automation routines.
"""

import threading
import time
from datetime import datetime
from typing import Callable, Dict, Any
from croniter import croniter


class Scheduler:
    """Cron-based scheduler for automation routines."""
    
    def __init__(self, automation_engine, time_provider=None):
        self.automation_engine = automation_engine
        self.time_provider = time_provider or datetime.now
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
    
    def start(self):
        """Start the scheduler background thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[Scheduler] Started")
    
    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        print("[Scheduler] Stopped")
    
    def tick(self):
        """Trigger check called by event bus time_tick."""
        try:
            with self._lock:
                self._check_triggers()
        except Exception as e:
            print(f"[Scheduler] Error in tick: {e}")

    def _run_loop(self):
        """Main scheduler loop."""
        while self.running:
            self.tick()
            # Sleep for a bit (resolution 1 sec is fine for now, but 5s is safer for resources)
            time.sleep(5)
    
    def _check_triggers(self):
        """Check all routines for time-based triggers."""
        now = self.time_provider()
        routines = self.automation_engine.list()
        
        for name, routine in routines.items():
            if not routine.get("enabled", True):
                continue
            
            trigger = routine.get("trigger", {})
            if trigger.get("type") != "time":
                continue
                
            schedule = trigger.get("cron") or trigger.get("schedule")
            if not schedule:
                continue
                
            # If schedule is "HH:MM", convert to cron "MM HH * * *"
            if ":" in schedule and len(schedule) == 5:
                hour, minute = schedule.split(":")
                schedule = f"{int(minute)} {int(hour)} * * *"
            
            try:
                # Check if next_run is set
                next_run_ts = routine.get("next_run")
                
                if next_run_ts is None:
                    # First time seeing this routine, calculate next run from now
                    iter = croniter(schedule, now)
                    next_run = iter.get_next(datetime)
                    self.automation_engine.modify(name, next_run=next_run.timestamp())
                    continue
                
                # Convert stored timestamp to datetime
                next_run = datetime.fromtimestamp(next_run_ts)
                
                if now >= next_run:
                    # Trigger!
                    print(f"[Scheduler] Triggering routine: {name} at {now}")
                    
                    # Execute in separate thread/process handled by engine
                    # But we should ensure we don't double-trigger if execution fails?
                    # Engine run is async usually or returns fast.
                    self.automation_engine.run(name)
                    
                    # Calculate NEXT run
                    # Use current time as base to avoid catching up on old missed events endlessly
                    # OR use next_run as base to keep strict schedule?
                    # For home automation, "catch up" is usually bad (lights flashing).
                    # Use NOW as base.
                    iter = croniter(schedule, now)
                    new_next_run = iter.get_next(datetime)
                    
                    self.automation_engine.modify(name, next_run=new_next_run.timestamp(), last_run=now.timestamp())
                    
            except Exception as e:
                print(f"[Scheduler] Error processing routine {name}: {e}")

    def get_next_run(self, schedule_str):
        """Utility to get next run time for UI."""
        try:
            # Convert HH:MM to cron
            if ":" in schedule_str and len(schedule_str) == 5:
                hour, minute = schedule_str.split(":")
                schedule_str = f"{int(minute)} {int(hour)} * * *"
                
            iter = croniter(schedule_str, self.time_provider())
            return iter.get_next(datetime)
        except:
            return None
