"""
User Pattern Store
------------------
Stores and retrieves user behavioral patterns for mission inference.
Integrates with Phase 1 Cognitive Memory (or standalone for MVP).
"""

import json
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict, field
import time

@dataclass
class UserPatterns:
    """User behavioral patterns"""
    user_id: str
    
    # Sleep patterns
    bedtime_variance_minutes: float = 0.0
    irregular_sleep_count: int = 0
    avg_bedtime_seconds: float = 0.0
    avg_waketime_seconds: float = 0.0
    
    # Energy patterns
    away_duration_hours: float = 0.0
    idle_device_count: int = 0
    
    # Work patterns
    work_pattern_consistency: float = 0.0
    avg_work_start_hour: int = 9
    avg_work_duration_hours: float = 8.0
    
    # Metadata
    last_updated_ts: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserPatterns':
        return cls(**data)


class UserPatternStore:
    """
    Persistent storage for user behavioral patterns.
    MVP: JSON files (upgradeable to Phase 1 Cognitive Memory integration).
    """
    
    def __init__(self, storage_path: str = "data/user_patterns"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
    def _get_pattern_file(self, user_id: str) -> Path:
        return self.storage_path / f"{user_id}_patterns.json"
    
    def save_patterns(self, patterns: UserPatterns):
        """Save user patterns to disk"""
        file_path = self._get_pattern_file(patterns.user_id)
        with open(file_path, 'w') as f:
            json.dump(patterns.to_dict(), f, indent=2)
    
    def load_patterns(self, user_id: str) -> Optional[UserPatterns]:
        """Load user patterns from disk"""
        file_path = self._get_pattern_file(user_id)
        if not file_path.exists():
            # Return default patterns
            return UserPatterns(user_id=user_id)
        
        with open(file_path, 'r') as f:
            data = json.load(f)
            return UserPatterns.from_dict(data)
    
    def update_sleep_patterns(self, user_id: str, bedtimes: List[float], waketimes: List[float]):
        """Update sleep-related patterns"""
        patterns = self.load_patterns(user_id)
        
        if bedtimes:
            import statistics
            patterns.avg_bedtime_seconds = statistics.mean(bedtimes)
            if len(bedtimes) > 1:
                patterns.bedtime_variance_minutes = statistics.stdev(bedtimes) / 60.0
        
        if waketimes:
            import statistics
            patterns.avg_waketime_seconds = statistics.mean(waketimes)
        
        patterns.last_updated_ts = time.time()
        self.save_patterns(patterns)
    
    def update_energy_patterns(self, user_id: str, away_hours: float, idle_count: int):
        """Update energy-related patterns"""
        patterns = self.load_patterns(user_id)
        patterns.away_duration_hours = away_hours
        patterns.idle_device_count = idle_count
        patterns.last_updated_ts = time.time()
        self.save_patterns(patterns)
    
    def update_work_patterns(self, user_id: str, consistency: float, start_hour: int, duration_hours: float):
        """Update work-related patterns"""
        patterns = self.load_patterns(user_id)
        patterns.work_pattern_consistency = consistency
        patterns.avg_work_start_hour = start_hour
        patterns.avg_work_duration_hours = duration_hours
        patterns.last_updated_ts = time.time()
        self.save_patterns(patterns)
    
    def get_patterns_as_dict(self, user_id: str) -> Dict:
        """Get patterns as dictionary for MissionInference"""
        patterns = self.load_patterns(user_id)
        return patterns.to_dict()
