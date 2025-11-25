"""
Cognitive Loop
--------------
Orchestrates the cognitive cycle:
1. Observe state
2. Update memory & context
3. Generate predictions
4. Propose actions
"""

import time
import threading
import queue
from typing import Dict, Any, List

from config.settings import get_config
from agent.event_bus.event_bus import EventBus
from agent_cognitive.memory_manager import MemoryManager
from agent_cognitive.context_graph import ContextGraph
from agent_cognitive.prediction_engine import PredictionEngine

CONFIG = get_config("cognitive")
LOOP_CONFIG = CONFIG.get("cognitive_loop", {})

class CognitiveLoop:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.memory = MemoryManager()
        self.context = ContextGraph()
        self.predictor = PredictionEngine(self.memory, self.context)
        
        self.running = False
        self.thread = None
        self.event_queue = queue.Queue()
        
        # Subscribe to events to update memory
        self.event_bus.subscribe("*", self._on_event)

    def start(self):
        """Start the background cognitive loop"""
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[CognitiveLoop] Started.")

    def stop(self):
        """Stop the background loop"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        print("[CognitiveLoop] Stopped.")

    def _on_event(self, event: Dict[str, Any]):
        """
        Callback for EventBus. 
        NON-BLOCKING: Just puts event in queue.
        """
        self.event_queue.put(event)

    def _loop(self):
        """Main background loop"""
        last_cycle_time = time.time()
        interval = LOOP_CONFIG.get("interval_minutes", 10) * 60
        
        while self.running:
            # 1. Process Event Queue (Batch or Continuous)
            self._process_queue()
            
            # 2. Run Prediction Cycle periodically
            if time.time() - last_cycle_time > interval:
                self.run_cycle()
                # 3. Cleanup expired context
                self.context.cleanup_expired_edges()
                last_cycle_time = time.time()
                
            time.sleep(0.1) # Prevent CPU spin

    def _process_queue(self):
        """Process pending events from queue"""
        while not self.event_queue.empty():
            try:
                event = self.event_queue.get_nowait()
                self._handle_event_sync(event)
                self.event_queue.task_done()
            except queue.Empty:
                break
            except Exception as e:
                print(f"[CognitiveLoop] Error processing event: {e}")

    def _handle_event_sync(self, event: Dict[str, Any]):
        """Handle event synchronously (called from background thread)"""
        # 1. Store in Memory (DB Write)
        self.memory.add_event(event)
        
        # 2. Update Context
        if event.get("type") == "location_change":
            user_id = event["payload"].get("user_id")
            new_loc = event["payload"].get("location")
            if user_id and new_loc:
                self.context.add_edge(user_id, new_loc, "is_in")
                
        elif event.get("type") == "routine_start":
            # Example: user -> doing -> routine
            user_id = event["payload"].get("user_id", "unknown_user")
            routine = event["payload"].get("name")
            if routine:
                # Ephemeral state: expires in 1 hour (3600s) by default for routines
                self.context.add_edge(user_id, routine, "is_doing", ttl=3600)

    def run_cycle(self):
        """
        Run the cognitive cycle: Observe -> Reason -> Act
        Stages:
        1. Snapshot State
        2. Safety Checks (High Priority)
        3. Maintenance Checks (Medium Priority)
        4. Predictive Comfort (Low Priority)
        5. Conflict Resolution & Publishing
        """
        try:
            # 1. Snapshot State (Mock for now, normally query ContextGraph)
            current_state = {
                "time": time.time(),
                "users": self.context.get_nodes_by_type("user"),
                "devices": self.context.get_nodes_by_type("device")
            }
            
            suggestions = []
            
            # 2. Safety Checks
            safety_alerts = self._check_safety(current_state)
            suggestions.extend(safety_alerts)
            
            # 3. Maintenance Checks
            if not safety_alerts: # Only check maintenance if safe
                maintenance = self._check_maintenance(current_state)
                suggestions.extend(maintenance)
            
            # 4. Predictive Comfort
            if not safety_alerts: # Only predict comfort if safe
                predictions = self.predictor.predict_next_actions(current_state)
                # Filter low confidence
                predictions = [p for p in predictions if p["confidence"] >= CONFIG.get("prediction", {}).get("confidence_threshold", 0.7)]
                suggestions.extend(predictions)
            
            # 5. Publish Suggestions
            for suggestion in suggestions:
                priority = suggestion.get("priority", "low")
                print(f"[CognitiveLoop] [{priority.upper()}] Suggestion: {suggestion}")
                
                self.event_bus.publish({
                    "type": "suggestion",
                    "source": "cognitive_loop",
                    "payload": suggestion
                })
                
        except Exception as e:
            print(f"[CognitiveLoop] Error in cycle: {e}")

    def _check_safety(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for safety anomalies"""
        alerts = []
        # Example: Check if front door is open and no one is home
        # This would require querying the graph for "is_in" edges
        # For MVP, we return empty list
        return alerts

    def _check_maintenance(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for routine maintenance"""
        suggestions = []
        # Example: Check if vacuum hasn't run in 3 days
        return suggestions
