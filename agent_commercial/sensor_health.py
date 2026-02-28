"""
Sensor Health Monitor
=====================

Handles the epistemic integrity of the sensory layer.
Validates data freshness, completeness, and variability.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import statistics

# Fix Import
from agent_commercial.bms_data_model import BMSDataPoint

class PerceptionState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLIND = "blind"

@dataclass
class HealthReport:
    state: PerceptionState
    stale_count: int
    frozen_count: int
    null_count: int
    total_sensors: int
    confidence_penalty: float
    details: List[str]

class SensorHealthMonitor:
    def __init__(self, stale_threshold_seconds=300, frozen_threshold_ticks=5):
        self.stale_threshold = stale_threshold_seconds
        self.frozen_votes: Dict[str, List[float]] = {} # {point_id: [last_5_values]}
        self.max_frozen_history = frozen_threshold_ticks
        
    def check_health(self, points: List[BMSDataPoint]) -> HealthReport:
        """
        Analyze a list of BMSDataPoint objects for health issues.
        """
        if not points:
            return HealthReport(PerceptionState.BLIND, 0, 0, 0, 0, 0.0, ["No sensors provided"])
            
        now = datetime.now()
        issues = []
        stale_cnt = 0
        frozen_cnt = 0
        null_cnt = 0
        
        for p in points:
            # 1. Null Check
            if p.value is None:
                null_cnt += 1
                issues.append(f"{p.point_id}: Value is None")
                continue
                
            # 2. Stale Check
            # Assuming p.timestamp is a datetime object
            if isinstance(p.timestamp, str):
                try:
                    ts = datetime.fromisoformat(p.timestamp)
                except (ValueError, TypeError) as e:
                    logger.debug(f"Timestamp parse fallback for {p.point_id}: {e}")
                    ts = now # Fallback
            else:
                ts = p.timestamp
                
            age = (now - ts).total_seconds()
            if age > self.stale_threshold:
                stale_cnt += 1
                issues.append(f"{p.point_id}: Stale data ({int(age)}s old)")
                
            # 3. Frozen Check (Variance)
            # Only for analytic/numeric values, not status/enums
            if isinstance(p.value, (int, float)):
                hist = self.frozen_votes.get(p.point_id, [])
                hist.append(p.value)
                if len(hist) > self.max_frozen_history:
                    hist.pop(0)
                self.frozen_votes[p.point_id] = hist
                
                if len(hist) >= self.max_frozen_history:
                    if len(set(hist)) == 1 and p.value != 0: # 0 might be valid off state
                        frozen_cnt += 1
                        issues.append(f"{p.point_id}: Frozen value ({p.value}) for {len(hist)} ticks")

        # Determine State
        total = len(points)
        bad_sensors = stale_cnt + null_cnt + frozen_cnt
        health_ratio = (total - bad_sensors) / total
        
        state = PerceptionState.HEALTHY
        penalty = 1.0
        
        if bad_sensors > 0:
            if bad_sensors / total > 0.3: # >30% bad
                state = PerceptionState.DEGRADED
                penalty = 0.6
            if bad_sensors / total > 0.8: # >80% bad
                state = PerceptionState.BLIND
                penalty = 0.1
                
        return HealthReport(
            state=state,
            stale_count=stale_cnt,
            frozen_count=frozen_cnt,
            null_count=null_cnt,
            total_sensors=total,
            confidence_penalty=penalty,
            details=issues[:5] # Limit detail log
        )
