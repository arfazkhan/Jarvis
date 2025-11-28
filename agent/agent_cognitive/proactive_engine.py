import time
import threading
import logging
import statistics
from typing import List, Dict, Any

class ProactiveEngine:
    """
    Analyzes historical state data to generate intelligent insights and suggestions.
    Detects behavioral drift and usage patterns.
    """
    def __init__(self, event_bus, state_engine, check_interval=3600):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.check_interval = check_interval # Default 1 hour
        
        self.running = False
        self.thread = None
        self.logger = logging.getLogger("ProactiveEngine")

    def start(self):
        """Start the analysis loop."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.thread.start()
        self.logger.info("ProactiveEngine analysis loop started")

    def stop(self):
        """Stop the analysis loop."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.logger.info("ProactiveEngine analysis loop stopped")

    def _analysis_loop(self):
        """Periodic analysis loop."""
        while self.running:
            try:
                self.analyze()
            except Exception as e:
                self.logger.error(f"Error in proactive analysis: {e}")
            
            # Sleep in chunks to allow faster stopping
            for _ in range(int(self.check_interval)):
                if not self.running:
                    break
                time.sleep(1.0)

    def analyze(self):
        """Perform analysis on history."""
        self.logger.info("Running proactive analysis...")
        history = self.state_engine.get_history()
        
        if not history:
            return

        # 1. Detect Bedtime Drift
        self._analyze_bedtime_drift(history)
        
        # 2. Detect Usage Anomalies (Simple)
        # self._analyze_usage_anomalies(history)

    def _analyze_bedtime_drift(self, history: List[Dict]):
        """
        Analyze 'light off' events in the bedroom to detect bedtime drift.
        """
        bedtime_timestamps = []
        
        for event in history:
            # Heuristic: "bedroom_light" turned "off" between 8PM and 4AM
            payload = event.get("payload", {})
            if event.get("type") == "state_changed" and \
               "bedroom" in payload.get("entity_id", "").lower() and \
               payload.get("new_state", {}).get("state") == "off":
                
                ts = event.get("timestamp", 0)
                struct_time = time.localtime(ts)
                hour = struct_time.tm_hour
                
                # Filter for night hours (20:00 - 04:00)
                if 20 <= hour <= 23 or 0 <= hour <= 4:
                    # Normalize to "minutes from 8PM" for averaging
                    minutes_from_8pm = (hour - 20) * 60 + struct_time.tm_min
                    if hour < 20: # Early morning (next day relative to 8PM)
                        minutes_from_8pm += 24 * 60
                    
                    bedtime_timestamps.append(minutes_from_8pm)

        if len(bedtime_timestamps) < 3:
            return # Not enough data

        # Calculate stats
        avg_minutes = statistics.mean(bedtime_timestamps)
        variance = statistics.variance(bedtime_timestamps) if len(bedtime_timestamps) > 1 else 0
        
        # Convert back to readable time
        avg_hour = int((avg_minutes / 60) + 20) % 24
        avg_min = int(avg_minutes % 60)
        
        self.logger.debug(f"Calculated avg bedtime: {avg_hour:02d}:{avg_min:02d} (Variance: {variance:.1f})")
        
        # Check for drift (e.g., if last 3 are significantly later than average)
        # For simplicity in this phase, we just report the insight if variance is high
        if variance > 3600: # High variance (> 1 hour spread)
            self._publish_insight(
                "sleep_variance", 
                f"Your bedtime has been varying by over an hour recently. Consistent sleep helps recovery."
            )
        elif avg_hour >= 1: # Average is after 1 AM
            self._publish_insight(
                "late_bedtime",
                f"You've been going to bed around {avg_hour:02d}:{avg_min:02d} lately. Want me to start the sleep routine earlier?"
            )

    def _publish_insight(self, insight_type: str, message: str):
        """Publish a proactive insight."""
        self.logger.info(f"Publishing insight: {insight_type} -> {message}")
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {
                "type": "proactive_insight",
                "subtype": insight_type,
                "source": "ProactiveEngine",
                "content": message
            }
        })
