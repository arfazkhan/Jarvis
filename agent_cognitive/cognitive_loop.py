"""
Cognitive Loop
--------------
Orchestrates the cognitive cycle for both residential and commercial modes:

Residential Mode:
  1. Observe device state
  2. Update memory & context
  3. Generate comfort predictions
  4. Propose smart home actions

Commercial Mode (BMS):
  1. Observe equipment state
  2. Analyze alarms & correlations
  3. Detect energy anomalies
  4. Generate maintenance predictions
  5. Propose operational insights
"""

import time
import threading
import queue
import logging
from typing import Dict, Any, List, Optional

from config.settings import get_config
from config.mode_dispatcher import ModeDispatcher, ArvisMode
from agent.event_bus.event_bus import EventBus
from agent_cognitive.memory_manager import MemoryManager
from agent_cognitive.context_graph import ContextGraph
from agent_cognitive.prediction_engine import PredictionEngine

logger = logging.getLogger("arvis.cognitive")

CONFIG = get_config("cognitive")
LOOP_CONFIG = CONFIG.get("cognitive_loop", {})


class CognitiveLoop:
    """
    Mode-aware cognitive loop that adapts behavior based on ARVIS_MODE.
    
    - Residential: Focus on comfort, convenience, energy saving
    - Commercial: Focus on equipment health, alarms, energy efficiency
    """
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.memory = MemoryManager()
        self.context = ContextGraph()
        self.predictor = PredictionEngine(self.memory, self.context)
        
        # Get mode configuration
        self.dispatcher = ModeDispatcher.get_instance()
        self.mode = self.dispatcher.mode
        
        # BMS-specific engines (lazy loaded in commercial mode)
        self._bms_state = None
        self._alarm_engine = None
        self._energy_analyzer = None
        self._pm_engine = None
        
        self.running = False
        self.thread = None
        self.event_queue = queue.Queue()
        
        # Subscribe to events to update memory
        self.event_bus.subscribe("*", self._on_event)
        
        logger.info(f"CognitiveLoop initialized in {self.mode.value} mode")

    def _init_bms_engines(self):
        """Initialize BMS engines for commercial mode"""
        if self.mode != ArvisMode.COMMERCIAL:
            return
        
        try:
            from agent_bms.bms_state_engine import BMSStateEngine
            from agent_bms.alarm_engine import AlarmEngine
            from agent_bms.energy_analyzer import EnergyAnalyzer
            from agent_bms.predictive_maintenance import PredictiveMaintenanceEngine
            
            self._bms_state = BMSStateEngine()
            self._alarm_engine = AlarmEngine()
            self._energy_analyzer = EnergyAnalyzer()
            self._pm_engine = PredictiveMaintenanceEngine()
            
            logger.info("BMS engines initialized for commercial mode")
        except ImportError as e:
            logger.warning(f"Could not initialize BMS engines: {e}")

    def start(self):
        """Start the background cognitive loop"""
        if self.running: 
            return
        
        # Initialize mode-specific engines
        if self.mode == ArvisMode.COMMERCIAL:
            self._init_bms_engines()
        
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        
        mode_name = self.dispatcher.config.name
        print(f"[CognitiveLoop] Started in {mode_name} mode.")

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
        
        # Commercial mode runs more frequently for real-time monitoring
        if self.mode == ArvisMode.COMMERCIAL:
            interval = min(interval, 300)  # Max 5 minutes for BMS
        
        while self.running:
            # 1. Process Event Queue (Batch or Continuous)
            self._process_queue()
            
            # 2. Run Prediction Cycle periodically
            if time.time() - last_cycle_time > interval:
                self.run_cycle()
                # 3. Cleanup expired context
                self.context.cleanup_expired_edges()
                last_cycle_time = time.time()
                
            time.sleep(0.1)  # Prevent CPU spin

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
                logger.error(f"Error processing event: {e}")

    def _handle_event_sync(self, event: Dict[str, Any]):
        """Handle event synchronously (called from background thread)"""
        # 1. Store in Memory (DB Write)
        self.memory.add_event(event)
        
        event_type = event.get("type", "")
        
        # Mode-specific event handling
        if self.mode == ArvisMode.RESIDENTIAL:
            self._handle_residential_event(event, event_type)
        else:
            self._handle_commercial_event(event, event_type)
    
    def _handle_residential_event(self, event: Dict[str, Any], event_type: str):
        """Handle residential (smart home) events"""
        if event_type == "location_change":
            user_id = event["payload"].get("user_id")
            new_loc = event["payload"].get("location")
            if user_id and new_loc:
                self.context.add_edge(user_id, new_loc, "is_in")
                
        elif event_type == "routine_start":
            user_id = event["payload"].get("user_id", "unknown_user")
            routine = event["payload"].get("name")
            if routine:
                self.context.add_edge(user_id, routine, "is_doing", ttl=3600)
    
    def _handle_commercial_event(self, event: Dict[str, Any], event_type: str):
        """Handle commercial (BMS) events"""
        payload = event.get("payload", {})
        
        if event_type == "bms_point_update":
            # Equipment data point updated
            equipment_id = payload.get("equipment_id")
            point_id = payload.get("point_id")
            value = payload.get("value")
            
            if equipment_id and point_id:
                self.context.add_edge(equipment_id, point_id, "has_point")
                # Store current value as node attribute
                self.context.update_node_attr(point_id, "value", value)
                
        elif event_type == "bms_alarm":
            # New alarm received
            alarm = payload.get("alarm")
            if alarm and self._alarm_engine:
                self._alarm_engine.ingest_alarm(alarm)
                
        elif event_type == "bms_energy_reading":
            # Energy meter reading
            reading = payload.get("reading")
            if reading and self._energy_analyzer:
                self._energy_analyzer.add_reading(reading)

    def run_cycle(self):
        """
        Run the cognitive cycle: Observe -> Reason -> Act
        
        Behavior depends on mode:
        - Residential: Comfort predictions, device suggestions
        - Commercial: Equipment health, alarm analysis, energy insights
        """
        try:
            if self.mode == ArvisMode.RESIDENTIAL:
                self._run_residential_cycle()
            else:
                self._run_commercial_cycle()
                
        except Exception as e:
            logger.error(f"Error in cognitive cycle: {e}")

    def _run_residential_cycle(self):
        """Residential mode cognitive cycle"""
        # 1. Snapshot State
        current_state = {
            "time": time.time(),
            "users": self.context.get_nodes_by_type("user"),
            "devices": self.context.get_nodes_by_type("device")
        }
        
        suggestions = []
        
        # 2. Safety Checks
        safety_alerts = self._check_residential_safety(current_state)
        suggestions.extend(safety_alerts)
        
        # 3. Maintenance Checks
        if not safety_alerts:
            maintenance = self._check_residential_maintenance(current_state)
            suggestions.extend(maintenance)
        
        # 4. Predictive Comfort
        if not safety_alerts:
            predictions = self.predictor.predict_next_actions(current_state)
            threshold = CONFIG.get("prediction", {}).get("confidence_threshold", 0.7)
            predictions = [p for p in predictions if p.get("confidence", 0) >= threshold]
            suggestions.extend(predictions)
        
        # 5. Publish Suggestions
        self._publish_suggestions(suggestions)

    def _run_commercial_cycle(self):
        """Commercial (BMS) mode cognitive cycle"""
        suggestions = []
        
        # 1. Equipment Health Check
        if self._bms_state and self._pm_engine:
            health_alerts = self._check_equipment_health()
            suggestions.extend(health_alerts)
        
        # 2. Alarm Analysis & Correlation
        if self._alarm_engine:
            alarm_insights = self._analyze_alarms()
            suggestions.extend(alarm_insights)
        
        # 3. Energy Anomaly Detection
        if self._energy_analyzer:
            energy_insights = self._analyze_energy()
            suggestions.extend(energy_insights)
        
        # 4. Predictive Maintenance
        if self._pm_engine:
            maintenance = self._check_predictive_maintenance()
            suggestions.extend(maintenance)
        
        # 5. Publish Insights
        self._publish_suggestions(suggestions, source="ops_copilot")

    def _check_equipment_health(self) -> List[Dict[str, Any]]:
        """Check equipment health status"""
        alerts = []
        
        try:
            # Get equipment with issues
            if hasattr(self._bms_state, 'get_equipment_with_issues'):
                issues = self._bms_state.get_equipment_with_issues()
                for eq in issues:
                    alerts.append({
                        "type": "equipment_health",
                        "priority": "high",
                        "equipment_id": eq.equipment_id,
                        "message": f"Equipment {eq.name} showing degraded performance",
                        "action": "Schedule inspection"
                    })
        except Exception as e:
            logger.debug(f"Equipment health check error: {e}")
        
        return alerts

    def _analyze_alarms(self) -> List[Dict[str, Any]]:
        """Analyze alarm patterns and correlations"""
        insights = []
        
        try:
            # Get alarm clusters (correlated alarms)
            clusters = self._alarm_engine.get_clusters()
            
            for cluster in clusters:
                if len(cluster.alarms) > 2:
                    # Multiple correlated alarms - likely root cause
                    root = cluster.root_cause or cluster.alarms[0]
                    insights.append({
                        "type": "alarm_correlation",
                        "priority": "high",
                        "cluster_id": cluster.cluster_id,
                        "alarm_count": len(cluster.alarms),
                        "probable_root_cause": root.equipment_id,
                        "message": f"Alarm cascade detected from {root.equipment_id}",
                        "action": "Investigate root cause equipment first"
                    })
            
            # Check for nuisance alarms
            priority_queue = self._alarm_engine.get_priority_queue()
            nuisance_count = sum(1 for a in priority_queue if a.is_nuisance)
            
            if nuisance_count > 5:
                insights.append({
                    "type": "nuisance_alarms",
                    "priority": "low",
                    "count": nuisance_count,
                    "message": f"{nuisance_count} nuisance alarms detected",
                    "action": "Review alarm setpoints and deadbands"
                })
                
        except Exception as e:
            logger.debug(f"Alarm analysis error: {e}")
        
        return insights

    def _analyze_energy(self) -> List[Dict[str, Any]]:
        """Detect energy waste patterns"""
        insights = []
        
        try:
            # Get waste patterns
            patterns = self._energy_analyzer.identify_waste_patterns()
            
            for pattern in patterns[:3]:  # Top 3 waste patterns
                insights.append({
                    "type": "energy_waste",
                    "priority": "medium",
                    "pattern_type": pattern.pattern_type.value,
                    "estimated_waste_kwh": pattern.estimated_waste_kwh,
                    "potential_savings_qar": pattern.potential_savings_qar,
                    "message": pattern.description,
                    "action": pattern.recommendation
                })
                
        except Exception as e:
            logger.debug(f"Energy analysis error: {e}")
        
        return insights

    def _check_predictive_maintenance(self) -> List[Dict[str, Any]]:
        """Generate predictive maintenance suggestions"""
        suggestions = []
        
        try:
            # Get high-risk equipment predictions
            # This would iterate through equipment and check predictions
            # For now, return empty - actual implementation would query PM engine
            pass
            
        except Exception as e:
            logger.debug(f"Predictive maintenance error: {e}")
        
        return suggestions

    def _check_residential_safety(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for safety anomalies (residential)"""
        alerts = []
        # Example: Check if front door is open and no one is home
        # This would require querying the graph for "is_in" edges
        return alerts

    def _check_residential_maintenance(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for routine maintenance (residential)"""
        suggestions = []
        # Example: Check if vacuum hasn't run in 3 days
        return suggestions

    def _publish_suggestions(
        self, 
        suggestions: List[Dict[str, Any]], 
        source: str = "cognitive_loop"
    ):
        """Publish suggestions to event bus"""
        for suggestion in suggestions:
            priority = suggestion.get("priority", "low")
            logger.info(f"[{priority.upper()}] {suggestion.get('message', suggestion)}")
            
            self.event_bus.publish({
                "type": "suggestion",
                "source": source,
                "mode": self.mode.value,
                "payload": suggestion
            })

    # ═══════════════════════════════════════════════════════════════════════
    # BMS ENGINE INJECTION (for testing and external configuration)
    # ═══════════════════════════════════════════════════════════════════════
    
    def set_bms_engines(
        self,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        pm_engine=None
    ):
        """
        Inject BMS engines from external source.
        
        Useful when BMS engines are already initialized elsewhere
        (e.g., in agent_bms.main).
        """
        if bms_state:
            self._bms_state = bms_state
        if alarm_engine:
            self._alarm_engine = alarm_engine
        if energy_analyzer:
            self._energy_analyzer = energy_analyzer
        if pm_engine:
            self._pm_engine = pm_engine
        
        logger.info("BMS engines injected into cognitive loop")

