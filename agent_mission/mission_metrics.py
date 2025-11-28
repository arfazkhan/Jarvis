"""
Mission Metrics
---------------
Tracks and computes mission-specific success metrics.
"""

from typing import Dict, List
from dataclasses import dataclass, field
import time
import statistics

@dataclass
class MissionMetric:
    """Single metric definition"""
    name: str
    target: str  # e.g., "< 30 minutes" or "> 0.8"
    current_value: float = 0.0
    weight: float = 1.0
    history: List[float] = field(default_factory=list)
    
    def update(self, value: float):
        """Update metric value and history"""
        self.current_value = value
        self.history.append(value)

class MissionMetrics:
    """
    Computes and tracks mission-specific KPIs.
    """
    
    def __init__(self):
        self.metrics: Dict[str, MissionMetric] = {}
        
    def add_metric(self, name: str, target: str, weight: float = 1.0):
        """Add a new metric to track"""
        self.metrics[name] = MissionMetric(
            name=name,
            target=target,
            weight=weight
        )
        
    def update_metric(self, name: str, value: float):
        """Update metric value"""
        if name in self.metrics:
            self.metrics[name].update(value)
        else:
            raise ValueError(f"Unknown metric: {name}")
    
    def get_metric(self, name: str) -> MissionMetric:
        """Get metric by name"""
        return self.metrics.get(name)
    
    def compute_overall_score(self) -> float:
        """Compute weighted overall mission success score (0-1)"""
        if not self.metrics:
            return 0.0
        
        total_weight = sum(m.weight for m in self.metrics.values())
        if total_weight == 0:
            return 0.0
        
        weighted_sum = 0.0
        for metric in self.metrics.values():
            # Normalize metric value to 0-1 range based on target
            # This is simplified - real implementation would parse target string
            metric_score = min(metric.current_value, 1.0)
            weighted_sum += metric_score * metric.weight
        
        return weighted_sum / total_weight
    
    def get_all_metrics(self) -> Dict[str, float]:
        """Get current values of all metrics"""
        return {name: m.current_value for name, m in self.metrics.items()}
    
    # Sleep Mission Metrics
    def compute_bedtime_variance(self, bedtimes: List[float]) -> float:
        """Compute standard deviation of bedtimes (in minutes)"""
        if len(bedtimes) < 2:
            return 0.0
        
        try:
            stdev_seconds = statistics.stdev(bedtimes)
            return stdev_seconds / 60.0
        except Exception:
            return 0.0
    
    def compute_wake_time_stability(self, wake_times: List[float]) -> float:
        """Compute stability score (0-1, higher is better)"""
        if len(wake_times) < 2:
            return 1.0
        
        try:
            stdev_seconds = statistics.stdev(wake_times)
            # Target: < 60 min stdev is acceptable.
            stdev_minutes = stdev_seconds / 60.0
            stability = max(0.0, 1.0 - (stdev_minutes / 60.0))
            return stability
        except Exception:
            return 0.0
    
    # Energy Mission Metrics
    def compute_device_off_ratio(self, off_time: float, total_time: float) -> float:
        """Compute ratio of time devices were off"""
        if total_time == 0:
            return 0.0
        return off_time / total_time
    
    # Security Mission Metrics
    def compute_presence_simulation_adherence(self, scheduled: int, executed: int) -> float:
        """Compute adherence to presence simulation schedule"""
        if scheduled == 0:
            return 1.0
        return executed / scheduled
