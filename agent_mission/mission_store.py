"""
Mission Store
-------------
Persistent storage for mission state.
Uses JSON files for MVP (can upgrade to SQLite later).
"""

import json
import os
from typing import Dict, List, Optional
from pathlib import Path
from agent_mission.base.mission import Mission, MissionStatus

class MissionStore:
    def __init__(self, storage_path: str = "data/missions"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
    def _get_mission_file(self, mission_id: str) -> Path:
        return self.storage_path / f"{mission_id}.json"
    
    def save_mission(self, mission: Mission):
        """Save mission to disk"""
        file_path = self._get_mission_file(mission.mission_id)
        with open(file_path, 'w') as f:
            json.dump(mission.to_dict(), f, indent=2)
    
    def load_mission(self, mission_id: str) -> Optional[Mission]:
        """Load mission from disk"""
        file_path = self._get_mission_file(mission_id)
        if not file_path.exists():
            return None
        
        with open(file_path, 'r') as f:
            data = json.load(f)
            return Mission.from_dict(data)
    
    def delete_mission(self, mission_id: str):
        """Delete mission file"""
        file_path = self._get_mission_file(mission_id)
        if file_path.exists():
            file_path.unlink()
    
    def list_missions(self, status: Optional[MissionStatus] = None) -> List[Mission]:
        """List all missions, optionally filtered by status"""
        missions = []
        for file_path in self.storage_path.glob("*.json"):
            with open(file_path, 'r') as f:
                data = json.load(f)
                mission = Mission.from_dict(data)
                if status is None or mission.status == status:
                    missions.append(mission)
        return missions
    
    def get_active_missions(self) -> List[Mission]:
        """Get all non-completed/archived missions"""
        active_statuses = [
            MissionStatus.INIT,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.MONITORING,
            MissionStatus.ADAPTING
        ]
        missions = []
        for status in active_statuses:
            missions.extend(self.list_missions(status))
        return missions
    
    def archive_mission(self, mission_id: str):
        """Move mission to archived status"""
        mission = self.load_mission(mission_id)
        if mission:
            mission.status = MissionStatus.ARCHIVED
            self.save_mission(mission)
