import logging
from typing import Dict, Any

class ConversationBridge:
    """
    Bridges the gap between Mission execution events and the Dialogue system.
    Translates technical events into natural language notifications.
    """
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.logger = logging.getLogger("ConversationBridge")
        
        # Subscribe to mission events
        self.event_bus.subscribe("mission_execution_started", self._on_mission_started)
        self.event_bus.subscribe("mission_execution_completed", self._on_mission_completed)
        self.event_bus.subscribe("mission_execution_failed", self._on_mission_failed)
        self.event_bus.subscribe("mission_step_completed", self._on_step_completed)

    def _on_mission_started(self, event: Dict[str, Any]):
        payload = event.get("payload", {})
        mission_id = payload.get("mission_id")
        self._notify(f"I've started the mission: {mission_id}")

    def _on_mission_completed(self, event: Dict[str, Any]):
        payload = event.get("payload", {})
        mission_id = payload.get("mission_id")
        self._notify(f"Mission {mission_id} completed successfully.")

    def _on_mission_failed(self, event: Dict[str, Any]):
        payload = event.get("payload", {})
        mission_id = payload.get("mission_id")
        error = payload.get("error", "Unknown error")
        self._notify(f"Mission {mission_id} failed: {error}")

    def _on_step_completed(self, event: Dict[str, Any]):
        # Optional: Verbose mode could announce every step.
        # For now, we'll skip step announcements to avoid spam, 
        # or maybe just log them.
        pass

    def _notify(self, message: str):
        """Publish a system notification for TTS/UI."""
        self.logger.info(f"Bridge Notification: {message}")
        self.event_bus.publish({
            "type": "system_notification",
            "payload": {
                "type": "mission_update",
                "source": "ConversationBridge",
                "content": message
            }
        })
