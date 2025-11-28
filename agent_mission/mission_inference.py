"""
Mission Inference Engine
-------------------------
Autonomously determines which missions should be activated based on:
- Sensor patterns (sleep variance, presence, energy usage)
- User behavior
- Historical data

Outputs confidence scores and respects debounce rules.
"""

import time
from typing import Dict, List, Optional
from agent_sensors.sensor_models import HomeSituation

class MissionInference:
    def __init__(self):
        self.last_auto_trigger: Dict[str, float] = {}  # mission_type -> last_trigger_ts
        self.debounce_period = 48 * 3600  # 48 hours in seconds
        
    def infer_mission(self, situation: HomeSituation, user_patterns: Dict) -> List[Dict[str, any]]:
        """
        Infer which missions should be started.
        
        Args:
            situation: Current HomeSituation from sensor fusion
            user_patterns: Historical patterns (sleep variance, etc.)
        
        Returns:
            List of mission recommendations with confidence scores
        """
        recommendations = []
        
        # 1. Sleep Optimization Inference
        sleep_conf = self._infer_sleep_optimization(situation, user_patterns)
        if sleep_conf > 0.5:
            recommendations.append({
                "mission_type": "sleep_optimization",
                "confidence": sleep_conf,
                "reason": "High bedtime variance detected"
            })
        
        # 2. Energy Saver Inference
        energy_conf = self._infer_energy_saver(situation, user_patterns)
        if energy_conf > 0.5:
            recommendations.append({
                "mission_type": "energy_saver",
                "confidence": energy_conf,
                "reason": "Extended absence or energy inefficiency detected"
            })
        
        # 3. Home Security Inference
        security_conf = self._infer_home_security(situation, user_patterns)
        if security_conf > 0.5:
            recommendations.append({
                "mission_type": "home_security",
                "confidence": security_conf,
                "reason": "User away for extended period"
            })
        
        # 4. Focus & Productivity Inference
        focus_conf = self._infer_focus_productivity(situation, user_patterns)
        if focus_conf > 0.5:
            recommendations.append({
                "mission_type": "focus_productivity",
                "confidence": focus_conf,
                "reason": "Repetitive work patterns detected"
            })
        
        # Filter by debounce
        filtered = []
        now = time.time()
        for rec in recommendations:
            mission_type = rec["mission_type"]
            last_trigger = self.last_auto_trigger.get(mission_type, 0)
            if now - last_trigger > self.debounce_period:
                filtered.append(rec)
        
        return filtered
        
    def _infer_sleep_optimization(self, situation: HomeSituation, patterns: Dict) -> float:
        """Infer sleep mission confidence"""
        confidence = 0.0
        
        # Check bedtime variance from patterns
        bedtime_variance = patterns.get("bedtime_variance_minutes", 0)
        if bedtime_variance > 45:
            confidence += 0.6
        elif bedtime_variance > 30:
            confidence += 0.4
        
        # Check irregular sleep patterns
        if patterns.get("irregular_sleep_count", 0) > 3:
            confidence += 0.3
        
        return min(confidence, 1.0)
        
    def _infer_energy_saver(self, situation: HomeSituation, patterns: Dict) -> float:
        """Infer energy saver mission confidence"""
        confidence = 0.0
        
        # Check if user is away
        if situation.home_presence.state == "away":
            away_duration_hours = patterns.get("away_duration_hours", 0)
            if away_duration_hours > 2:
                confidence += 0.7
        
        # Check idle device count
        idle_device_count = patterns.get("idle_device_count", 0)
        if idle_device_count > 3:
            confidence += 0.3
        
        return min(confidence, 1.0)
        
    def _infer_home_security(self, situation: HomeSituation, patterns: Dict) -> float:
        """Infer security mission confidence"""
        confidence = 0.0
        
        # Primary trigger: extended absence
        if situation.home_presence.state == "away":
            away_duration_hours = patterns.get("away_duration_hours", 0)
            if away_duration_hours > 1:
                confidence += 0.8
        
        return min(confidence, 1.0)
        
    def _infer_focus_productivity(self, situation: HomeSituation, patterns: Dict) -> float:
        """Infer focus mission confidence"""
        confidence = 0.0
        
        # Check for repetitive work patterns
        work_pattern_consistency = patterns.get("work_pattern_consistency", 0.0)
        if work_pattern_consistency > 0.7:
            confidence += 0.5
        
        # Check if currently in work mode
        if situation.activity_hint == "working":
            confidence += 0.3
        
        return min(confidence, 1.0)
        
    def mark_auto_triggered(self, mission_type: str):
        """Record that a mission was auto-triggered (for debounce)"""
        self.last_auto_trigger[mission_type] = time.time()
