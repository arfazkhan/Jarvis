"""
Interaction Loop
----------------
Orchestrates the flow between user input (Voice/Text), the DialogueManager (Brain),
and the system outputs (TTS, Actions, Missions).
"""

from typing import Dict, Any, Optional
from agent.event_bus.event_bus import EventBus
from agent_conversation.dialogue_manager import DialogueManager, DialogueResult

class InteractionLoop:
    def __init__(self, event_bus: EventBus, dialogue_manager: DialogueManager):
        self.event_bus = event_bus
        self.dialogue_manager = dialogue_manager
        
        # Subscribe to inputs
        self.event_bus.subscribe("voice_input", self.handle_voice_input)
        self.event_bus.subscribe("text_input", self.handle_text_input)
        
        # Subscribe to system notifications (Proactive)
        self.event_bus.subscribe("system_notification", self.handle_system_notification)
        
    def handle_voice_input(self, event: Dict[str, Any]):
        """Handle voice input event"""
        payload = event.get("payload", {})
        text = payload.get("text")
        if not text: return
        
        self._process_input(text, source="voice")
        
    def handle_text_input(self, event: Dict[str, Any]):
        """Handle text input event"""
        payload = event.get("payload", {})
        text = payload.get("text")
        if not text: return
        
        self._process_input(text, source="text")
        
    def _process_input(self, text: str, source: str):
        """Process input via DialogueManager and handle results"""
        result = self.dialogue_manager.process_input(text)
        
        # 1. Handle Response (TTS / Text)
        if result.response_text:
            if source == "voice" and result.should_speak:
                self.event_bus.publish({
                    "type": "voice_response",
                    "source": "interaction_loop",
                    "payload": {"text": result.response_text}
                })
            else:
                self.event_bus.publish({
                    "type": "text_response",
                    "source": "interaction_loop",
                    "payload": {"text": result.response_text}
                })
                
        # 2. Handle Action Request
        if result.action_request:
            self.event_bus.publish({
                "type": "action_request",
                "source": "interaction_loop",
                "payload": result.action_request
            })
            
        # 3. Handle Mission Command
        if result.mission_command:
            command = result.mission_command.get("command")
            if command == "start":
                self.event_bus.publish({
                    "type": "mission_started",
                    "source": "interaction_loop",
                    "payload": {
                        "mission_id": result.mission_command.get("mission_id"),
                        "trigger": result.mission_command.get("trigger", "user_command")
                    }
                })
            elif command == "stop":
                self.event_bus.publish({
                    "type": "mission_stopped", # Or mission_cancel_requested
                    "source": "interaction_loop",
                    "payload": {
                        "mission_id": result.mission_command.get("mission_id")
                    }
                })
            elif command == "status":
                # Maybe trigger a status check event or just let the response handle it?
                # For now, response text covers it, but we could emit an event to query status
                pass

    def handle_system_notification(self, event: Dict[str, Any]):
        """Handle proactive system notifications"""
        payload = event.get("payload", {})
        message = payload.get("message")
        priority = payload.get("priority", "normal")
        
        if not message: return
        
        # For high priority or if configured, speak it
        if priority == "high" or payload.get("speak", False):
            self.event_bus.publish({
                "type": "voice_response",
                "source": "interaction_loop",
                "payload": {"text": message}
            })
        else:
            # Just log or text response
            self.event_bus.publish({
                "type": "text_response",
                "source": "interaction_loop",
                "payload": {"text": message}
            })
