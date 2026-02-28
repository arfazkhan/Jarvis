from agent_home.persistence.state_persistence import StatePersistence
import time


class StateEngine:
    def __init__(self, event_bus, persist_path="data/state.json", max_history_size=1000):
        self.event_bus = event_bus
        self.persistence = StatePersistence(persist_path)
        self.max_history_size = max_history_size
        
        # Load state from disk or use defaults
        loaded_state = self.persistence.load_state()
        self.state = {
            "devices": loaded_state.get("devices", {}),
            "history": loaded_state.get("history", [])
        }
        
        self.devices = self.state["devices"]  # Alias for compatibility
        self.history = self.state["history"]  # Alias for compatibility
        
        # Persistence optimizations
        self.last_save_time = 0
        self.min_save_interval = 1.0  # Max 1 save per second
        self.dirty = False

        event_bus.subscribe("relay_toggled", self.handle_event)
        event_bus.subscribe("time_tick", self.handle_event)
        # Subscribe to other relevant events for history
        event_bus.subscribe("voice_command", self.handle_event)
        event_bus.subscribe("routine_triggered", self.handle_event)

    def handle_event(self, event):
        # Defensive check for event type
        if not isinstance(event, dict):
            print(f"[StateEngine] Warning: Expected dict event, got {type(event)}")
            return
            
        # Keep history limited to avoid memory issues long term
        self.state["history"].append(event)
        # self.history is a reference to self.state["history"], so it updates automatically
        
        # Rotate history if it exceeds the limit
        while len(self.state["history"]) > self.max_history_size:
            self.state["history"].pop(0)

        state_changed = False

        if event.get("type") == "relay_toggled":
            payload = event.get("payload", {})
            device = payload.get("device")
            endpoint = payload.get("endpoint")
            new_state = payload.get("state")

            if device and endpoint is not None:
                if device not in self.state["devices"]:
                    self.state["devices"][device] = {}
                
                # Check if state actually changed to avoid unnecessary saves
                current_val = self.state["devices"][device].get(endpoint)
                if current_val != new_state:
                    self.state["devices"][device][endpoint] = new_state
                    state_changed = True
        
        # Persist if significant change (DEBOUNCED)
        if state_changed:
            now = time.time()
            if now - self.last_save_time > self.min_save_interval:
                self._save_to_disk()
                self.last_save_time = now
                self.dirty = False
            else:
                self.dirty = True
        
        # Periodically save history or pending changes
        if event.get("type") == "time_tick":
             # Force save if dirty, or periodic history save
             now = time.time()
             if self.dirty or (int(event.get("timestamp", 0)) % 60 < 5): 
                 self._save_to_disk()
                 self.last_save_time = now
                 self.dirty = False

    def _save_to_disk(self):
        """Persist current state to disk."""
        full_state = {
            "devices": self.state["devices"],
            "history": self.state["history"],
            "last_updated": time.time()
        }
        self.persistence.save_state(full_state)

    def summary(self):
        # Create a human-readable summary for the LLM
        device_summary = []
        for dev, endpoints in self.state["devices"].items():
            status = ", ".join([f"Ep{ep}:{st}" for ep, st in endpoints.items()])
            device_summary.append(f"{dev}: [{status}]")
        
        return f"Devices: {'; '.join(device_summary) if device_summary else 'No devices active'}"

    def get_history(self, limit=100):
        """Get recent event history."""
        return self.state["history"][-limit:]

    def update(self, updates: dict):
        """Update state directly (used for testing/internal updates)."""
        self.state.update(updates)
        return self.state["history"][-100:] if self.state["history"] else []

    def set_state(self, updates: dict):
        """Alias for update (compatibility)."""
        return self.update(updates)
    
    def get_state(self):
        """Get current device state (alias for compatibility)."""
        return self.state["devices"]
    
    def get_default_state(self):
        """Get default empty state structure."""
        return {
            "devices": {},
            "history": [],
            "last_updated": time.time()
        }
