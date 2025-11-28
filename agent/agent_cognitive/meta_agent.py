import threading
import time
import logging
from typing import Dict, Any, Optional

class MetaAgent:
    """
    The 'Brainstem' of the system.
    Continuously evaluates state, mission status, and safety to make proactive decisions.
    """
    def __init__(self, event_bus, state_engine, mission_manager, safety_validator, check_interval=1.0):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.mission_manager = mission_manager
        self.safety_validator = safety_validator
        self.check_interval = check_interval
        
        self.running = False
        self.thread = None
        self.logger = logging.getLogger("MetaAgent")
        
        # Cognitive State
        self.focus = "idle"  # idle, monitoring, active_mission, safety_alert
        self.urgency = 0.0   # 0.0 to 1.0
        self.last_thought_time = 0
        
        # Subscribe to key events
        self.event_bus.subscribe("state_changed", self._on_state_change)
        self.event_bus.subscribe("mission_status_changed", self._on_mission_status)
        self.event_bus.subscribe("safety_violation", self._on_safety_violation)

    def start(self):
        """Start the cognitive loop."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._cognitive_loop, daemon=True)
        self.thread.start()
        self.logger.info("MetaAgent cognitive loop started")
        print("[MetaAgent] Cognitive loop started")

    def stop(self):
        """Stop the cognitive loop."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.logger.info("MetaAgent cognitive loop stopped")

    def _cognitive_loop(self):
        """The main thinking loop."""
        while self.running:
            try:
                self._think()
            except Exception as e:
                self.logger.error(f"Error in cognitive loop: {e}")
            
            time.sleep(self.check_interval)

    def _think(self):
        """Evaluate situation and decide on actions."""
        now = time.time()
        self.last_thought_time = now
        
        # 1. Evaluate Safety (Highest Priority)
        # (Safety validator usually pushes events, but we can double check active alerts)
        # TODO: Check safety_validator status if exposed
        
        # 2. Evaluate Missions
        active_missions = self.mission_manager.get_active_missions()
        if active_missions:
            self.focus = "active_mission"
            # Check for stagnation (e.g., mission running too long without step completion)
            # This requires mission start times which we might need to fetch
            pass
        else:
            self.focus = "monitoring"

        # 3. Evaluate State Patterns (Drift)
        # TODO: Integrate with ProactiveEngine when available
        
        # 4. Decide "Should I Act?"
        if self.urgency > 0.8:
            self._trigger_proactive_action()

    def _on_state_change(self, event):
        """Handle state changes."""
        # Minor updates might not trigger a full re-think, but major ones should
        # For now, just log or update internal tracking
        pass

    def _on_mission_status(self, event):
        """Handle mission status updates."""
        status = event.get("payload", {}).get("status")
        if status == "FAILED":
            self.urgency += 0.5 # Spike urgency on failure
            self.logger.warning(f"Mission failed, increasing urgency to {self.urgency}")
        elif status == "COMPLETED":
            self.urgency = max(0.0, self.urgency - 0.2) # Reduce urgency

    def _on_safety_violation(self, event):
        """Handle safety violations."""
        self.focus = "safety_alert"
        self.urgency = 1.0
        self.logger.critical("Safety violation detected! Max urgency.")
        # MetaAgent might trigger a specific recovery mission here

    def _trigger_proactive_action(self):
        """Trigger a proactive action or suggestion."""
        self.logger.info("Triggering proactive action due to high urgency")
        print("[MetaAgent] 💡 I have a proactive suggestion...")
        
        # Reset urgency after acting
        self.urgency = 0.0
        
        # Publish event for InteractionLoop to pick up
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {
                "type": "proactive_suggestion",
                "source": "MetaAgent",
                "content": "I noticed something requires attention." # Placeholder
            }
        })
