"""
Mission Monitor
---------------
Continuously evaluates mission performance and triggers adaptations.
"""

import time
from typing import Dict, Optional
from agent.event_bus.event_bus import EventBus
from agent_mission.mission_store import MissionStore
from agent_mission.mission_metrics import MissionMetrics
from agent_mission.base.mission import Mission, MissionStatus

class MissionMonitor:
    def __init__(self, event_bus: EventBus, store: MissionStore):
        self.event_bus = event_bus
        self.store = store
        self.mission_metrics: Dict[str, MissionMetrics] = {}
        
        # Subscribe to mission events
        self.event_bus.subscribe("mission_started", self._on_mission_started)
        self.event_bus.subscribe("mission_step_completed", self._on_step_completed)
        
    def _on_mission_started(self, event: Dict):
        """Initialize metrics when mission starts"""
        mission_id = event["payload"]["mission_id"]
        self.mission_metrics[mission_id] = MissionMetrics()
        print(f"📊 Monitoring started for mission: {mission_id}")
        
    def _on_step_completed(self, event: Dict):
        """Update metrics when step completes"""
        mission_id = event["payload"].get("mission_id")
        step_id = event["payload"].get("step_id")
        print(f"✅ Step completed: {step_id} in {mission_id}")
        
    def evaluate_mission(self, mission_id: str, sensor_data: Dict) -> Dict:
        """
        Evaluate mission performance based on current data.
        
        Args:
            mission_id: Mission to evaluate
            sensor_data: Current sensor readings
        
        Returns:
            Evaluation dict with scores and recommendations
        """
        mission = self.store.load_mission(mission_id)
        if not mission:
            return {"error": "Mission not found"}
        
        metrics = self.mission_metrics.get(mission_id)
        if not metrics:
            return {"error": "No metrics initialized"}
        
        # Compute mission-specific metrics
        if mission.mission_type == "sleep_optimization":
            evaluation = self._evaluate_sleep_mission(mission, sensor_data, metrics)
        elif mission.mission_type == "energy_saver":
            evaluation = self._evaluate_energy_mission(mission, sensor_data, metrics)
        elif mission.mission_type == "home_security":
            evaluation = self._evaluate_security_mission(mission, sensor_data, metrics)
        elif mission.mission_type == "focus_productivity":
            evaluation = self._evaluate_focus_mission(mission, sensor_data, metrics)
        else:
            evaluation = {"score": 0.5, "needs_adaptation": False}
        
        # Update mission metrics
        mission.metrics = evaluation.get("metrics", {})
        self.store.save_mission(mission)
        
        return evaluation
        
    def _evaluate_sleep_mission(self, mission: Mission, data: Dict, metrics: MissionMetrics) -> Dict:
        """Evaluate sleep optimization mission"""
        # Extract bedtime data
        bedtimes = data.get("bedtimes", [])
        wake_times = data.get("wake_times", [])
        night_motion = data.get("night_motion_count", 0)
        
        evaluation = {
            "mission_id": mission.mission_id,
            "metrics": {},
            "score": 0.0,
            "needs_adaptation": False,
            "recommendations": []
        }
        
        # Compute bedtime variance
        if bedtimes:
            variance = metrics.compute_bedtime_variance(bedtimes)
            evaluation["metrics"]["bedtime_variance"] = variance
            
            # Check if needs adaptation
            if variance > 45:
                evaluation["needs_adaptation"] = True
                evaluation["recommendations"].append("adjust_bedtime_scene_timing")
        
        #  Compute wake time stability
        if wake_times:
            stability = metrics.compute_wake_time_stability(wake_times)
            evaluation["metrics"]["wake_time_stability"] = stability
        
        # Night motion
        evaluation["metrics"]["night_motion_count"] = night_motion
        if night_motion > 10:
            evaluation["needs_adaptation"] = True
            evaluation["recommendations"].append("reduce_bedroom_temperature")
        
        # Overall score (simplified)
        metrics_count = len(evaluation["metrics"])
        if metrics_count > 0:
            # Simple average for MVP - adjusted for more realistic scoring
            variance_value = evaluation["metrics"].get("bedtime_variance", 0)
            # Variance of 10 min is perfect (1.0), variance of 60 min is poor (0.0)
            variance_score = max(0, 1.0 - (variance_value / 60.0))
            
            stability_score = evaluation["metrics"].get("wake_time_stability", 0.5)
            motion_score = max(0, 1.0 - (night_motion / 20.0))
            
            evaluation["score"] = (variance_score + stability_score + motion_score) / 3.0
        
        return evaluation
        
    def _evaluate_energy_mission(self, mission: Mission, data: Dict, metrics: MissionMetrics) -> Dict:
        """Evaluate energy saver mission"""
        off_time = data.get("device_off_time_hours", 0)
        total_time = data.get("total_time_hours", 24)
        
        off_ratio = metrics.compute_device_off_ratio(off_time, total_time)
        
        evaluation = {
            "mission_id": mission.mission_id,
            "metrics": {
                "device_off_ratio": off_ratio
            },
            "score": off_ratio,
            "needs_adaptation": off_ratio < 0.5,
            "recommendations": []
        }
        
        if off_ratio < 0.5:
            evaluation["recommendations"].append("increase_idle_detection_aggressiveness")
        
        return evaluation
        
    def _evaluate_security_mission(self, mission: Mission, data: Dict, metrics: MissionMetrics) -> Dict:
        """Evaluate home security mission"""
        scheduled_events = data.get("scheduled_presence_events", 0)
        executed_events = data.get("executed_presence_events", 0)
        
        adherence = metrics.compute_presence_simulation_adherence(scheduled_events, executed_events)
        
        evaluation = {
            "mission_id": mission.mission_id,
            "metrics": {
                "presence_simulation_adherence": adherence
            },
            "score": adherence,
            "needs_adaptation": adherence < 0.8,
            "recommendations": []
        }
        
        return evaluation
        
    def _evaluate_focus_mission(self, mission: Mission, data: Dict, metrics: MissionMetrics) -> Dict:
        """Evaluate focus productivity mission"""
        focus_sessions = data.get("focus_session_count", 0)
        interruptions = data.get("interruption_count", 0)
        
        # Score based on focus sessions and low interruptions
        session_score = min(focus_sessions / 2.0, 1.0)  # Target: 2+ sessions/day
        interruption_score = max(0, 1.0 - (interruptions / 10.0))  # Penalty for interruptions
        
        score = (session_score + interruption_score) / 2.0
        
        evaluation = {
            "mission_id": mission.mission_id,
            "metrics": {
                "focus_session_count": focus_sessions,
                "interruption_count": interruptions
            },
            "score": score,
            "needs_adaptation": interruptions > 5,
            "recommendations": []
        }
        
        if interruptions > 5:
            evaluation["recommendations"].append("increase_do_not_disturb_strictness")
        
        return evaluation
    
    def check_completion(self, mission_id: str) -> bool:
        """
        Check if mission should be auto-completed.
        
        Returns True if mission goal is achieved and stable.
        """
        mission = self.store.load_mission(mission_id)
        if not mission:
            return False
        
        # Check if mission has been running long enough
        runtime = time.time() - mission.start_ts
        if runtime < 3 * 24 * 3600:  # At least 3 days
            return False
        
        # Check if metrics are stable and good
        if not mission.metrics:
            return False
        
        # Mission-specific completion criteria
        if mission.mission_type == "sleep_optimization":
            variance = mission.metrics.get("bedtime_variance", 100)
            stability = mission.metrics.get("wake_time_stability", 0)
            return variance < 30 and stability > 0.8
        elif mission.mission_type == "energy_saver":
            off_ratio = mission.metrics.get("device_off_ratio", 0)
            return off_ratio > 0.7
        
        return False
