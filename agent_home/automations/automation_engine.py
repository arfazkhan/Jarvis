import threading
import time
import os
from agent_home.persistence.state_persistence import StatePersistence
from agent_home.automations.scheduler import Scheduler


class AutomationEngine:
    def __init__(self, event_bus, device_controller=None, state_engine=None, persist_path="data/routines.json", time_provider=None):
        self.event_bus = event_bus
        self.device_controller = device_controller
        self.state_engine = state_engine
        
        # Initialize persistence
        os.makedirs(os.path.dirname(persist_path) if os.path.dirname(persist_path) else "data", exist_ok=True)
        self.persistence = StatePersistence(persist_path)
        self.routines = self.persistence.load_state().get("routines", {})
        
        print(f"[AutomationEngine] Loaded {len(self.routines)} routines from disk")
        
        # Rate-limiting for hardware safety (CRITICAL)
        self.last_toggle = {}  # {endpoint: timestamp}
        self.min_toggle_interval = 0.5  # 500ms minimum between toggles
        
        # Subscribe to events that might trigger routines
        self.event_bus.subscribe("time_tick", self.check_triggers)
        self.event_bus.subscribe("relay_toggled", self.check_triggers)
        self.event_bus.subscribe("presence_update", self.check_triggers)
        
        # Initialize and start scheduler
        self.scheduler = Scheduler(self, time_provider=time_provider)
        self.scheduler.start()

    def create(self, name, trigger, actions, conditions=None):
        """
        Create a new automation routine.

        actions can be:
        - Simple list: ["control_relay(1, on)", "control_relay(2, on)"] 
        - Multi-step with delays: 
          [
            {"action": "control_relay", "args": [1, "on"]},
            {"action": "wait", "duration": 300},
            {"action": "control_relay", "args": [3, "on"]}
          ]
        conditions: Optional list of conditions like [{"presence": "home"}]
        """
        print(f"[AutomationEngine] Creating routine: {name}")
        self.routines[name] = {
            "trigger": trigger, 
            "actions": actions,
            "enabled": True,
            "conditions": conditions or []
        }
        self._save_to_disk()

    def run(self, name):
        """Execute a routine by name."""
        if name not in self.routines:
            print(f"[AutomationEngine] Routine '{name}' not found")
            return []
        
        routine = self.routines[name]
        if not routine.get("enabled", True):
            print(f"[AutomationEngine] Routine '{name}' is disabled")
            return []
        
        # Check conditions before running
        conditions = routine.get("conditions", [])
        if conditions and not self._check_conditions(conditions):
            print(f"[AutomationEngine] Conditions not met for routine '{name}', skipping")
            return []
        
        print(f"[AutomationEngine] Running routine: {name}")
        actions = routine["actions"]
        
        # Check if this is a multi-step routine
        if actions and isinstance(actions[0], dict):
            # Run in separate thread to not block
            threading.Thread(target=self._execute_multi_step, args=(name, actions)).start()
        else:
            # Simple action list - Execute immediately
            print(f"[AutomationEngine] Executing simple routine: {name}")
            for action in actions:
                self.execute_action(action)
            return actions
    
    def _execute_multi_step(self, routine_name, steps):
        """Execute a multi-step routine with delays and conditions."""
        print(f"[AutomationEngine] Executing multi-step routine: {routine_name}")
        
        for i, step in enumerate(steps):
            action = step.get("action")
            
            if action == "wait":
                duration = step.get("duration", 0)
                print(f"[AutomationEngine] Step {i+1}: Waiting {duration}s")
                time.sleep(duration)
            
            elif action == "control_relay":
                args = step.get("args", [])
                if len(args) >= 2 and self.device_controller:
                    relay, state = args[0], args[1]
                    print(f"[AutomationEngine] Step {i+1}: Control relay {relay} -> {state}")
                    self.device_controller.control_relay(relay, state)
            
            elif action == "if_no_motion":
                # Conditional: only proceed if no motion detected
                location = step.get("location")
                
                # Check state engine for motion status
                has_motion = False
                if self.state_engine:
                    # Assume state engine tracks motion sensors in "devices" or a dedicated "sensors" section
                    # For now, we iterate devices to find motion sensors in the location
                    # This is a simplification; a real system might have a spatial index
                    for dev_id, dev_state in self.state_engine.get_state().items():
                        # Check if device is in location and is a motion sensor (heuristic)
                        # In a real app, we'd check metadata. Here we assume naming convention or specific attributes.
                        if location.lower() in dev_id.lower() and "motion" in dev_id.lower():
                            if dev_state.get("motion") == "detected" or dev_state.get("occupancy") == "occupied":
                                has_motion = True
                                break
                
                if has_motion:
                    print(f"[AutomationEngine] Motion detected in {location}, skipping conditional action")
                else:
                    # No motion, execute
                    then_action = step.get("then_action")
                    then_args = step.get("args", [])
                    if then_action == "control_relay" and len(then_args) >= 2:
                        relay, state = then_args[0], then_args[1]
                        print(f"[AutomationEngine] Step {i+1}: Conditional - Control relay {relay} -> {state}")
                        if self.device_controller:
                            self.device_controller.control_relay(relay, state)
            
            elif action == "log_note":
                text = step.get("text", "")
                print(f"[AutomationEngine] Step {i+1}: NOTE: {text}")
        
        print(f"[AutomationEngine] Completed multi-step routine: {routine_name}")

    def modify(self, name, **updates):
        """Modify an existing routine."""
        if name not in self.routines:
            print(f"[AutomationEngine] Cannot modify - routine '{name}' not found")
            return False
        
        self.routines[name].update(updates)
        self._save_to_disk()
        print(f"[AutomationEngine] Modified routine: {name}")
        return True

    def list(self):
        """List all routines."""
        return self.routines
    
    def get_routine(self, name):
        """Get a routine by name."""
        return self.routines.get(name)
    
    def delete(self, name):
        """Delete a routine."""
        if name in self.routines:
            del self.routines[name]
            self._save_to_disk()
            print(f"[AutomationEngine] Deleted routine: {name}")
            return True
        return False
    
    def stop_all(self):
        """
        Emergency stop - stop all running automations and prevent new ones from starting.
        
        This is a safety-critical method called during emergency shutdown.
        """
        print("[AutomationEngine] ⛔ EMERGENCY STOP - Stopping all automations...")
        
        # 1. Stop the scheduler
        if self.scheduler:
            try:
                self.scheduler.stop()
                print("[AutomationEngine] ✅ Scheduler stopped")
            except Exception as e:
                print(f"[AutomationEngine] ⚠️ Error stopping scheduler: {e}")
        
        # 2. Disable all routines
        disabled_count = 0
        for name in self.routines:
            self.routines[name]["enabled"] = False
            disabled_count += 1
        
        print(f"[AutomationEngine] ✅ Disabled {disabled_count} routines")
        
        # 3. Publish emergency event
        if self.event_bus:
            self.event_bus.publish({
                "type": "emergency_shutdown",
                "source": "automation_engine",
                "timestamp": time.time(),
                "message": "All automations stopped via emergency stop"
            })
        
        # 4. Save state to disk
        self._save_to_disk()
        
        print("[AutomationEngine] ⛔ All automations STOPPED")
        return {"status": "stopped", "routines_disabled": disabled_count}
    
    def resume_all(self):
        """
        Resume automations after emergency stop.
        
        Call this when the emergency condition is cleared.
        """
        print("[AutomationEngine] 🟢 Resuming all automations...")
        
        # 1. Re-enable all routines
        enabled_count = 0
        for name in self.routines:
            self.routines[name]["enabled"] = True
            enabled_count += 1
        
        # 2. Restart the scheduler
        if self.scheduler:
            try:
                self.scheduler.start()
                print("[AutomationEngine] ✅ Scheduler restarted")
            except Exception as e:
                print(f"[AutomationEngine] ⚠️ Error restarting scheduler: {e}")
        
        # 3. Save state
        self._save_to_disk()
        
        print(f"[AutomationEngine] 🟢 Resumed {enabled_count} routines")
        return {"status": "resumed", "routines_enabled": enabled_count}
    
    def execute_action(self, action_str):
        """
        Execute a single action string with rate-limiting.
        
        Args:
            action_str: Action string like "control_relay(1, on)"
        
        Returns:
            bool: True if executed, False if rate-limited
        """
        # Parse action string
        if "control_relay" in action_str:
            # Extract endpoint and state
            # Format: "control_relay(1, on)" or "control_relay(1, 'on')"
            import re
            match = re.search(r'control_relay\((\d+),\s*[\'\"]?(\w+)[\'\"]?\)', action_str)
            if match:
                endpoint = int(match.group(1))
                state = match.group(2)
                
                # CRITICAL: Rate-limiting check
                now = time.time()
                last_time = self.last_toggle.get(endpoint, 0)
                
                if now - last_time < self.min_toggle_interval:
                    print(f"[AutomationEngine] RATE-LIMITED: Endpoint {endpoint} toggled too recently")
                    return False
                
                # Execute
                if self.device_controller:
                    self.device_controller.control_relay(endpoint, state)
                    self.last_toggle[endpoint] = now
                    return True
        
        return False

    def check_triggers(self, event):
        """Check if any routine should be triggered by this event."""
        # Run scheduler tick for time-based triggers
        self.scheduler.tick()
        
        # Check event-based triggers
        for name, routine in self.routines.items():
            if not routine.get("enabled", True):
                continue
                
            trigger = routine.get("trigger", {})
            if trigger.get("type") == "event":
                if self._match_event(trigger, event):
                    print(f"[AutomationEngine] Trigger matched for routine: {name}")
                    self.run(name)

    def _match_event(self, trigger, event):
        """
        Match a trigger definition against an event.
        
        Trigger format:
        {
            "type": "event",
            "event_type": "relay_toggled",
            "payload": {"device": "light1", "state": "on"} # Optional partial match
        }
        """
        # 1. Match event type
        if trigger.get("event_type") != event.get("type"):
            return False
            
        # 2. Match payload (if specified)
        trigger_payload = trigger.get("payload", {})
        event_payload = event.get("payload", {})
        
        for key, value in trigger_payload.items():
            if event_payload.get(key) != value:
                return False
                
        return True
    
    def _save_to_disk(self):
        """Persist routines to disk."""
        try:
            # Save routines as part of state
            state = self.persistence.load_state()
            state["routines"] = self.routines
            self.persistence.save_state(state)
            print(f"[AutomationEngine] Saved {len(self.routines)} routines to disk")
        except Exception as e:
            print(f"[AutomationEngine] Error saving routines: {e}")
    
    def _check_conditions(self, conditions):
        """
        Check if all conditions are met.
        
        Conditions format: [{"presence": "home"}, {"motion": "none"}]
        """
        if not self.state_engine:
            # Default to True if no state engine (unless strict mode required)
            return True
            
        for condition in conditions:
            for key, expected_value in condition.items():
                # Check against state engine's top-level state (e.g. "presence")
                # or nested state if we implement deeper logic
                current_value = self.state_engine.state.get(key)
                
                # Simple equality check
                if current_value != expected_value:
                    print(f"[AutomationEngine] Condition failed: {key} ({current_value}) != {expected_value}")
                    return False
        
        return True
