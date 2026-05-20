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
from arvis_core.event_bus.event_bus import EventBus
from agent_cognitive.memory_manager import MemoryManager
from agent_cognitive.context_graph import ContextGraph
from agent_cognitive.prediction_engine import PredictionEngine
from agent_advisory.goal_generator import GoalGenerator, GoalDiscoveryEngine
from agent_cognitive.meta_cognition import MetaCognition

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
        self._energy_analyzer = None
        self._pm_engine = None
        self._fleet_intelligence = None
        
        # New Agentic Engines
        self.goal_generator = None
        self.goal_discovery = None
        self.goal_tracker = None
        self.meta_cognition = MetaCognition() # Always available (uses shared DB)
        
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
            from agent_commercial.bms_state_engine import BMSStateEngine
            from agent_commercial.alarm_engine import AlarmEngine
            from agent_commercial.energy_analyzer import EnergyAnalyzer
            from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine
            from agent_commercial.fleet_intelligence import FleetIntelligence
            
            self._bms_state = BMSStateEngine()
            self._alarm_engine = AlarmEngine()
            self._energy_analyzer = EnergyAnalyzer()
            self._pm_engine = PredictiveMaintenanceEngine()
            self._fleet_intelligence = FleetIntelligence()

            # Wire alarm-resolved → skillbook write (state machine, not LLM-optional)
            self._bms_state.on_alarm_resolved(self._on_event)
            
            # Initialize Goal Discovery Stack
            self.goal_generator = GoalGenerator(
                fleet_intelligence=self._fleet_intelligence,
                predictive_engine=self._pm_engine,
                energy_analyzer=self._energy_analyzer,
                world_model=None # Circular dep if we add WorldModel here, can inject later
            )
            
            # Auto-discovery with 15 minute interval (900s)
            self.goal_discovery = GoalDiscoveryEngine(
                goal_generator=self.goal_generator,
                event_bus=self.event_bus,
                check_interval_seconds=900
            )

            # Goal Execution Tracker — subscribes to discovery events, tracks lifecycle
            from agent_advisory.goal_execution_tracker import GoalExecutionTracker
            self.goal_tracker = GoalExecutionTracker(
                event_bus=self.event_bus,
                bms_state=self._bms_state,
                remind_after_hours=24.0,
                expire_after_days=7,
                max_reminders=3,
            )

            logger.info("BMS engines, Goal Discovery, and Goal Tracker initialized for commercial mode")
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
        
        _last_retrain_check = 0.0
        _RETRAIN_CHECK_INTERVAL = 3600  # hourly

        while self.running:
            # 1. Process Event Queue (Batch or Continuous)
            self._process_queue()

            # 2. Run Prediction Cycle periodically
            if time.time() - last_cycle_time > interval:
                self.run_cycle()
                # 3. Cleanup expired context
                self.context.cleanup_expired_edges()
                last_cycle_time = time.time()

            # 4. M4.2: Hourly retrain trigger check
            if time.time() - _last_retrain_check > _RETRAIN_CHECK_INTERVAL:
                _last_retrain_check = time.time()
                try:
                    import asyncio as _asyncio
                    from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
                    _sched = get_retrain_scheduler()
                    _loop = _asyncio.new_event_loop()
                    _results = _loop.run_until_complete(_sched.check_and_execute())
                    _loop.close()
                    if _results:
                        logger.info(f"[CognitiveLoop] RetrainScheduler executed {len(_results)} retrain(s)")
                except Exception as _re:
                    logger.debug(f"[CognitiveLoop] RetrainScheduler check failed: {_re}")

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

        elif event_type == "bms_alarm_resolved":
            # Alarm resolved → programmatic skillbook write
            # This fires regardless of whether ARVIS mentioned skillbook in its response.
            alarm = payload.get("alarm", {})
            resolution = payload.get("resolution_summary", "")
            equipment_id = alarm.get("equipment_id") or payload.get("equipment_id")
            if equipment_id and resolution:
                import threading as _threading
                _threading.Thread(
                    target=self._write_resolved_fault_sync,
                    args=(equipment_id, alarm.get("alarm_type", "unknown"), resolution),
                    daemon=True,
                ).start()

        elif event_type == "bms_energy_reading":
            # Energy meter reading
            reading = payload.get("reading")
            if reading and self._energy_analyzer:
                self._energy_analyzer.add_reading(reading)

    def _write_resolved_fault_sync(
        self,
        equipment_id: str,
        alarm_type: str,
        resolution_summary: str,
    ) -> None:
        """Sync thread wrapper — runs the async skillbook write in a new event loop."""
        import asyncio as _asyncio
        try:
            loop = _asyncio.new_event_loop()
            loop.run_until_complete(
                self._write_resolved_fault_to_skillbook(
                    equipment_id, alarm_type, resolution_summary
                )
            )
        except Exception as e:
            logger.warning(f"[Skillbook] Sync write thread failed: {e}")
        finally:
            loop.close()

    async def _write_resolved_fault_to_skillbook(
        self,
        equipment_id: str,
        alarm_type: str,
        resolution_summary: str,
    ) -> None:
        """
        State-machine triggered skillbook write on alarm resolution.
        Fires from event bus — not LLM-optional.
        """
        try:
            from agent_advisory.knowledge_base import TechnicalKnowledgeBase
            kb = TechnicalKnowledgeBase()
            if hasattr(kb, "add_skill"):
                await kb.add_skill(
                    title=f"{equipment_id} — {alarm_type} resolved",
                    description=resolution_summary,
                    skill_type="fault_pattern",
                    equipment_id=equipment_id,
                    confidence=0.75,
                    tags=[equipment_id, alarm_type, "auto_recorded"],
                )
                logger.info(
                    f"[Skillbook] Fault resolution recorded: {equipment_id} / {alarm_type}"
                )
        except Exception as e:
            logger.warning(f"[Skillbook] Resolution write failed (non-fatal): {e}")

    def _act_on_prediction(self, prediction) -> None:
        """If prediction confidence > threshold, publish a proactive advisory."""
        threshold = CONFIG.get("prediction", {}).get("confidence_threshold", 0.7)
        if prediction.confidence < threshold:
            return

        predicted = prediction.predicted or {}
        advisory = {
            "type": "proactive_prediction",
            "priority": "medium",
            "prediction_type": prediction.prediction_type.value if hasattr(prediction.prediction_type, 'value') else str(prediction.prediction_type),
            "confidence": prediction.confidence,
            "horizon_minutes": prediction.horizon_minutes,
            "predicted_values": predicted,
            "message": f"Predicted {prediction.prediction_type.value}: confidence {prediction.confidence:.0%}",
        }

        # Escalate to high priority if energy anomaly or equipment degradation
        if predicted.get("total_power_kw", 0) > 500:
            advisory["priority"] = "high"
            advisory["message"] = f"High energy demand predicted ({predicted['total_power_kw']:.0f} kW) in {prediction.horizon_minutes}min"

        self.event_bus.publish({
            "type": "proactive_advisory",
            "source": "cognitive_loop",
            "mode": self.mode.value,
            "payload": advisory,
        })
        logger.info(f"[CognitiveLoop] Proactive advisory: {advisory['message']}")

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

        # 4.5. Filter degradation trend scan (runs every cycle, lightweight)
        if self._pm_engine and hasattr(self._pm_engine, "filter_predictor"):
            try:
                filter_warnings = self._pm_engine.filter_predictor.scan_all_filters()
                for fw in filter_warnings:
                    if fw.risk_level in ("high", "critical"):
                        suggestions.append({
                            "type": "filter_degradation",
                            "priority": fw.risk_level,
                            "equipment_id": fw.equipment_id,
                            "message": fw.recommendation,
                            "projected_days": fw.projected_days_to_threshold,
                            "confidence": fw.confidence,
                            "current_dp_pa": fw.current_dp_pa,
                        })
            except Exception as e:
                logger.debug(f"Filter degradation scan skipped: {e}")

        # 4.6. Energy Demand Prediction → Act
        try:
            from agent_cognitive.prediction_engine import PredictionType
            prediction = self.predictor.predict_next_actions({})
            if hasattr(prediction, 'confidence'):
                self._act_on_prediction(prediction)
        except Exception as e:
            logger.debug(f"Prediction step skipped: {e}")

        # 5. Proactive Goal Discovery (NEW)
        if self.goal_discovery:
            # Building ID is needed - assume context graph has it or default
            building_id = self.dispatcher.config.get("building_id", "default")
            new_goals = self.goal_discovery.run_discovery_cycle(building_id)
            if new_goals:
                logger.info(f"Discovered {len(new_goals)} proactive goals")

        # 5.1 Goal Execution Tracking — check status of active goals (read-only)
        if self.goal_tracker:
            try:
                self.goal_tracker.check_all_goals()
            except Exception as _e:
                logger.debug(f"[CognitiveLoop] Goal tracker check failed: {_e}")
                
        # 6. PHASE 4: Background Dreaming — real Monte Carlo What-If via Queen Swarm
        if int(time.time()) % 3600 < 300:
            try:
                from arvis_core.swarm.queen import QueenCoordinator
                from agent_commercial.swarm_nodes import build_swarm_nodes
                logger.info("[CognitiveLoop] Initiating Swarm Background Dreaming...") 
                nodes = build_swarm_nodes()
                dreaming_queen = QueenCoordinator()
                for node in nodes[:4]:  # Use only P0 (perception) nodes for efficiency
                    dreaming_queen.register_node(node)
                import asyncio
                dream_query = (
                    "Run a proactive Monte Carlo what-if analysis on the current BMS state. "
                    "Identify any hidden energy waste, comfort drift, or equipment degradation "
                    "patterns that are NOT currently triggering active alarms but could become "
                    "critical in the next 72 hours. List specific equipment IDs and recommended actions."
                )
                loop = asyncio.get_event_loop()
                dream_result = loop.run_until_complete(
                    dreaming_queen.execute_swarm(dream_query, {})
                )
                dream_advice = dream_result.get("advice", "")
                if dream_advice:
                    self.event_bus.publish({
                        "type": "proactive_discovery",
                        "source": "background_dreaming",
                        "mode": self.mode.value,
                        "payload": {"insight": dream_advice, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    })
                    logger.info(f"[CognitiveLoop] Proactive insight published from Background Dream.")
            except Exception as e:
                logger.warning(f"[CognitiveLoop] Background Dreaming cycle failed: {e}")

        # 7. PHASE 4: Nightly Knowledge Distillation (run once per day window)
        if int(time.time()) % 86400 < 300:
            try:
                import asyncio
                from agent_cognitive.distiller import run_distiller
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(run_distiller(building_id="default"))
                logger.info(f"[CognitiveLoop] Nightly Distillation complete: {result}")
            except Exception as e:
                logger.warning(f"[CognitiveLoop] Nightly Distillation failed: {e}")

        # 8. Meta-Cognition Reflection (once per hour)
        if int(time.time()) % 3600 < 300:
            reflection = self.meta_cognition.reflect()
            if reflection.get("calibration", {}).get("verdict") == "overconfident":
                logger.warning("[CognitiveLoop] Meta-Cognition: Overconfidence detected. Increasing EWC++ importance.")

        # 7. LLM cross-signal synthesis (when ≥2 distinct signal types present)
        if len(set(s.get("type") for s in suggestions)) >= 2:
            self._synthesize_cross_signal_insight(suggestions)

        # 8. Publish Insights
        self._publish_suggestions(suggestions, source="ops_copilot")

    def _synthesize_cross_signal_insight(self, suggestions: List[Dict[str, Any]]) -> None:
        """
        Use LLM to synthesize a cross-signal narrative when multiple signal types
        co-occur (e.g. filter degradation + energy waste + alarm cascade on same
        equipment), then publish as a 'cross_signal_insight' event.

        Runs synchronously in the cognitive background thread via run_until_complete.
        Gracefully no-ops if no LLM is available or the call fails.
        """
        try:
            from agent_unified.llm import UnifiedLLM
            import asyncio

            llm = UnifiedLLM()

            signal_lines = []
            for s in suggestions[:8]:
                sig_type = s.get("type", "unknown")
                equip = s.get("equipment_id", "")
                msg = s.get("message", "")
                priority = s.get("priority", "")
                signal_lines.append(
                    f"[{priority.upper()}] {sig_type}"
                    + (f" / {equip}" if equip else "")
                    + f": {msg}"
                )

            prompt = (
                "You are an expert BMS intelligence engine for a large commercial building in Qatar.\n"
                "The following simultaneous signals were detected this cycle. "
                "Synthesize them into ONE cohesive insight paragraph (3–5 sentences) for the facility manager. "
                "If multiple signals point to the same root cause or equipment, say so explicitly. "
                "Be concise, specific, and action-oriented. Do NOT use bullet points.\n\n"
                "Signals:\n" + "\n".join(signal_lines)
            )

            async def _call() -> str:
                resp = await llm.chat([{"role": "user", "content": prompt}])
                return (resp.content or "").strip()

            loop = asyncio.get_event_loop()
            insight_text = loop.run_until_complete(_call())

            if insight_text:
                self.event_bus.publish({
                    "type": "cross_signal_insight",
                    "source": "cognitive_loop_llm",
                    "mode": self.mode.value,
                    "payload": {
                        "insight": insight_text,
                        "signal_count": len(suggestions),
                        "signal_types": list({s.get("type") for s in suggestions}),
                        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                })
                logger.info("[CognitiveLoop] Cross-signal LLM insight published.")
        except Exception as exc:
            logger.debug("Cross-signal LLM synthesis skipped: %s", exc)

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
        """
        Generate predictive maintenance suggestions.
        PHASE 4 (Hindsight Replay): When a CRITICAL alarm fires, trigger Counterfactual
        Replay — ask the Swarm to re-evaluate the past 24h of data with hindsight knowledge
        of the failure, and update EWC++ confidence scores accordingly.
        """
        suggestions = []
        
        try:
            if self._alarm_engine:
                priority_queue = self._alarm_engine.get_priority_queue()
                critical_alarms = [a for a in priority_queue if getattr(a, 'priority', 'low') == 'critical']
                
                if critical_alarms:
                    for alarm in critical_alarms[:2]:  # Limit to 2 concurrent replays
                        equipment_id = getattr(alarm, 'equipment_id', 'unknown')
                        logger.info(f"[CognitiveLoop/HindsightReplay] Critical alarm detected for {equipment_id}. Triggering replay.")
                        suggestions.append({
                            "type": "hindsight_replay",
                            "priority": "critical",
                            "equipment_id": equipment_id,
                            "message": f"CRITICAL: {equipment_id} tripped. Running Hindsight Replay to check for missed signals.",
                            "action": "Backtracing 24h telemetry and re-evaluating agent predictions."
                        })
                        # Update EWC++ — if we missed a critical alarm, our predictive confidence was wrong
                        try:
                            self.meta_cognition.update_ewc_weights(
                                rule_name=f"missed_critical_{equipment_id}",
                                new_weight=-0.8,
                                importance=2.5
                            )
                        except Exception as ewc_e:
                            logger.debug(f"EWC++ update skipped: {ewc_e}")
                            
        except Exception as e:
            logger.debug(f"Predictive maintenance/hindsight error: {e}")
        
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
    # CHECKPOINTING & WARM-START
    # ═══════════════════════════════════════════════════════════════════════

    def save_checkpoint(self, db=None) -> bool:
        """Persist cognitive state for warm-start recovery."""
        try:
            import json
            import sqlite3

            if db is None:
                from agent_commercial.database import get_database
                db = get_database()

            conn = sqlite3.connect(str(db.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cognitive_checkpoints (
                    component TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            now = time.strftime("%Y-%m-%dT%H:%M:%S")

            # Save energy baselines from predictor
            if hasattr(self.predictor, '_energy_baseline'):
                conn.execute(
                    "INSERT OR REPLACE INTO cognitive_checkpoints (component, state_json, timestamp) VALUES (?, ?, ?)",
                    ("energy_baseline", json.dumps(self.predictor._energy_baseline), now),
                )

            # Save performance baselines
            if hasattr(self.predictor, '_performance_baselines'):
                conn.execute(
                    "INSERT OR REPLACE INTO cognitive_checkpoints (component, state_json, timestamp) VALUES (?, ?, ?)",
                    ("performance_baselines", json.dumps(self.predictor._performance_baselines), now),
                )

            # Save transition patterns
            if hasattr(self.predictor, '_transition_patterns'):
                conn.execute(
                    "INSERT OR REPLACE INTO cognitive_checkpoints (component, state_json, timestamp) VALUES (?, ?, ?)",
                    ("transition_patterns", json.dumps(self.predictor._transition_patterns), now),
                )

            # Save meta-cognition state
            if self.meta_cognition:
                meta_state = {
                    "ewc_weights": getattr(self.meta_cognition, '_ewc_weights', {}),
                    "decision_count": getattr(self.meta_cognition, '_decision_count', 0),
                }
                conn.execute(
                    "INSERT OR REPLACE INTO cognitive_checkpoints (component, state_json, timestamp) VALUES (?, ?, ?)",
                    ("meta_cognition", json.dumps(meta_state, default=str), now),
                )

            conn.commit()
            conn.close()
            logger.info("Cognitive checkpoint saved")
            return True
        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")
            return False

    def load_checkpoint(self, db=None) -> bool:
        """Restore cognitive state from last checkpoint."""
        try:
            import json
            import sqlite3

            if db is None:
                from agent_commercial.database import get_database
                db = get_database()

            conn = sqlite3.connect(str(db.db_path))
            cursor = conn.execute("SELECT component, state_json FROM cognitive_checkpoints")
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                logger.info("No cognitive checkpoint found — cold start")
                return False

            for component, state_json in rows:
                state = json.loads(state_json)

                if component == "energy_baseline" and hasattr(self.predictor, '_energy_baseline'):
                    self.predictor._energy_baseline = state
                elif component == "performance_baselines" and hasattr(self.predictor, '_performance_baselines'):
                    self.predictor._performance_baselines = state
                elif component == "transition_patterns" and hasattr(self.predictor, '_transition_patterns'):
                    self.predictor._transition_patterns = state
                elif component == "meta_cognition" and self.meta_cognition:
                    if hasattr(self.meta_cognition, '_ewc_weights'):
                        self.meta_cognition._ewc_weights = state.get("ewc_weights", {})
                    if hasattr(self.meta_cognition, '_decision_count'):
                        self.meta_cognition._decision_count = state.get("decision_count", 0)

            logger.info(f"Cognitive checkpoint restored ({len(rows)} components)")
            return True
        except Exception as e:
            logger.error(f"Checkpoint load failed: {e}")
            return False

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
        (e.g., in agent_commercial.main).
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

