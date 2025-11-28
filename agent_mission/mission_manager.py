"""
Mission Manager
---------------
Central controller for mission lifecycle.
Manages mission start/stop, state transitions, and persistence.
"""

import yaml
from typing import Dict, Optional, List
from pathlib import Path
from agent.event_bus.event_bus import EventBus
from agent_mission.base.mission import Mission, MissionStatus
from agent_mission.base.mission_context import MissionContext
from agent_mission.mission_store import MissionStore

class MissionManager:
    def __init__(self, event_bus: EventBus, template_dir: str = "agent_mission/templates"):
        self.event_bus = event_bus
        self.store = MissionStore()
        self.template_dir = Path(template_dir)
        self.templates: Dict[str, Dict] = {}
        self._load_templates()
        
    def _load_templates(self):
        """Load all mission templates from YAML files"""
        for template_file in self.template_dir.glob("*.yaml"):
            with open(template_file, 'r') as f:
                template = yaml.safe_load(f)
                self.templates[template["mission_id"]] = template
                
    def start_mission(self, mission_type: str, context: MissionContext, user_override: bool = False) -> Mission:
        """
        Start a new mission.
        
        Args:
            mission_type: Type of mission (sleep_optimization, etc.)
            context: Mission execution context
            user_override: If True, skip debounce and auto-start checks
        
        Returns:
            Created Mission object
        """
        # Check if template exists
        if mission_type not in self.templates:
            raise ValueError(f"Unknown mission type: {mission_type}")
        
        # Check for existing active mission of same type
        active = self.store.get_active_missions()
        for m in active:
            if m.mission_type == mission_type:
                raise ValueError(f"Mission {mission_type} already active")
        
        # Create mission
        mission = Mission(
            mission_id=f"{mission_type}_{int(context.created_ts)}",
            mission_type=mission_type,
            status=MissionStatus.INIT,
            context=context.to_dict(),
            user_id=context.user_id,
            start_ts=context.created_ts
        )
        
        # Save and publish event
        self.store.save_mission(mission)
        self.event_bus.publish({
            "type": "mission_started",
            "source": "mission_manager",
            "payload": {
                "mission_id": mission.mission_id,
                "mission_type": mission_type,
                "user_id": context.user_id
            }
        })
        
        print(f"✅ Mission started: {mission.mission_id}")
        return mission
        
    def stop_mission(self, mission_id: str, reason: str = "user_requested"):
        """Stop an active mission"""
        mission = self.store.load_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")
        
        if mission.status in [MissionStatus.COMPLETED, MissionStatus.ARCHIVED]:
            raise ValueError(f"Mission already finished: {mission_id}")
        
        mission.status = MissionStatus.COMPLETED
        mission.history.append({
            "event": "mission_stopped",
            "reason": reason,
            "ts": mission.start_ts
        })
        
        self.store.save_mission(mission)
        self.event_bus.publish({
            "type": "mission_stopped",
            "source": "mission_manager",
            "payload": {
                "mission_id": mission_id,
                "reason": reason
            }
        })
        
        print(f"✅ Mission stopped: {mission_id}")
        
    def get_status(self, mission_id: str) -> Dict:
        """Get mission status and metrics"""
        mission = self.store.load_mission(mission_id)
        if not mission:
            return {"error": "Mission not found"}
        
        return {
            "mission_id": mission.mission_id,
            "type": mission.mission_type,
            "status": mission.status.value,
            "metrics": mission.metrics,
            "start_ts": mission.start_ts,
            "next_run_ts": mission.next_run_ts
        }
        
    def list_active_missions(self) -> List[str]:
        """List all active mission IDs"""
        active = self.store.get_active_missions()
        return [m.mission_id for m in active]
        
    def update_mission_status(self, mission_id: str, new_status: MissionStatus):
        """Update mission status and publish event"""
        mission = self.store.load_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")
        
        old_status = mission.status
        mission.status = new_status
        mission.history.append({
            "event": "status_change",
            "from": old_status.value,
            "to": new_status.value,
            "ts": mission.start_ts
        })
        
        self.store.save_mission(mission)
        self.event_bus.publish({
            "type": "mission_status_changed",
            "source": "mission_manager",
            "payload": {
                "mission_id": mission_id,
                "old_status": old_status.value,
                "new_status": new_status.value
            }
        })
