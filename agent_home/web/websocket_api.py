"""
ARVIS WebSocket API
--------------------
Real-time bidirectional communication for voice commands and device control.

Events:
  Client -> Server:
    - voice_command: {text: "turn on kitchen light"}
    - device_command: {device_id: "kitchen_main", action: "turn_on"}
    - get_device_states: {}
    
  Server -> Client:
    - command_result: {success: bool, message: str, tool_calls: [...]}
    - device_state_update: {device_id: str, state: {...}}
    - tts_response: {text: str}
    - error: {message: str}
"""

import logging
import time
from typing import Dict, Any, Optional
from flask_socketio import SocketIO, emit, join_room, leave_room

logger = logging.getLogger(__name__)

# Global references (injected from main.py)
socketio: Optional[SocketIO] = None
event_bus = None
hybrid_orchestrator = None
state_engine = None
memory_orchestrator = None

# Connected clients
connected_clients: Dict[str, Dict] = {}


def init_websocket(app, bus, orchestrator, state, memory):
    """
    Initialize WebSocket server.
    
    Args:
        app: Flask application
        bus: EventBus instance
        orchestrator: HybridOrchestrator instance
        state: StateEngine instance
        memory: MemoryOrchestrator instance
    """
    global socketio, event_bus, hybrid_orchestrator, state_engine, memory_orchestrator
    
    socketio = SocketIO(
        app, 
        cors_allowed_origins="*",
        async_mode='threading',  # Use threading for Windows compatibility
        logger=False,
        engineio_logger=False
    )
    
    event_bus = bus
    hybrid_orchestrator = orchestrator
    state_engine = state
    memory_orchestrator = memory
    
    # Subscribe to ARVIS events and broadcast to clients
    if event_bus:
        event_bus.subscribe("agent_response", _on_agent_response)
        event_bus.subscribe("tool_calls_generated", _on_tool_calls)
        event_bus.subscribe("device_state_changed", _on_device_state_changed)
    
    # Register WebSocket event handlers
    _register_handlers()
    
    logger.info("[WebSocket] Initialized with ARVIS components")
    return socketio


def _register_handlers():
    """Register all WebSocket event handlers."""
    
    @socketio.on('connect')
    def handle_connect():
        from flask import request
        client_id = request.sid
        connected_clients[client_id] = {
            "connected_at": time.time(),
            "last_command": None
        }
        logger.info(f"[WebSocket] Client connected: {client_id}")
        emit('connected', {
            "message": "Connected to ARVIS",
            "client_id": client_id
        })
    
    @socketio.on('disconnect')
    def handle_disconnect():
        from flask import request
        client_id = request.sid
        if client_id in connected_clients:
            del connected_clients[client_id]
        logger.info(f"[WebSocket] Client disconnected: {client_id}")
    
    @socketio.on('voice_command')
    def handle_voice_command(data):
        """
        Handle voice command from client.
        
        Expected data: {"text": "turn on kitchen light"}
        """
        from flask import request
        client_id = request.sid
        text = data.get("text", "").strip()
        
        if not text:
            emit('error', {"message": "Empty command"})
            return
        
        logger.info(f"[WebSocket] Voice command from {client_id}: '{text}'")
        
        # Track the command
        if client_id in connected_clients:
            connected_clients[client_id]["last_command"] = {
                "text": text,
                "timestamp": time.time()
            }
        
        # Send to ARVIS via event bus
        if event_bus:
            event_bus.publish({
                "type": "voice_command",
                "payload": {
                    "text": text,
                    "source": "websocket",
                    "client_id": client_id
                }
            })
            emit('command_received', {
                "text": text,
                "status": "processing"
            })
        else:
            emit('error', {"message": "ARVIS not connected"})
    
    @socketio.on('device_command')
    def handle_device_command(data):
        """
        Direct device control command.
        
        Expected data: {
            "device_id": "kitchen_main",
            "action": "turn_on",  # or "turn_off", "set_brightness", etc.
            "args": {}  # optional additional args
        }
        """
        device_id = data.get("device_id")
        action = data.get("action")
        args = data.get("args", {})
        
        if not device_id or not action:
            emit('error', {"message": "Missing device_id or action"})
            return
        
        logger.info(f"[WebSocket] Device command: {action} -> {device_id}")
        
        # Convert to tool call format and publish
        if event_bus:
            tool_call = {
                "tool": action,
                "args": {"device_id": device_id, **args}
            }
            event_bus.publish({
                "type": "tool_calls_generated",
                "payload": [tool_call],
                "source": "websocket_direct"
            })
            emit('command_received', {
                "device_id": device_id,
                "action": action,
                "status": "executing"
            })
        else:
            emit('error', {"message": "ARVIS not connected"})
    
    @socketio.on('get_device_states')
    def handle_get_states():
        """Get current state of all devices."""
        if state_engine:
            try:
                states = state_engine.get_all_states() if hasattr(state_engine, 'get_all_states') else {}
                emit('device_states', {"devices": states})
            except Exception as e:
                emit('error', {"message": f"Failed to get states: {e}"})
        else:
            emit('error', {"message": "State engine not available"})
    
    @socketio.on('get_stats')
    def handle_get_stats():
        """Get ARVIS system statistics."""
        stats = {
            "connected_clients": len(connected_clients),
            "memory": memory_orchestrator.get_stats() if memory_orchestrator else None,
            "alias_resolver": hybrid_orchestrator.get_alias_stats() if hybrid_orchestrator else None
        }
        emit('stats', stats)
    
    @socketio.on('teach_alias')
    def handle_teach_alias(data):
        """
        Teach a new device alias.
        
        Expected data: {"alias": "reading lamp", "device_id": "bedroom_lamp"}
        """
        alias = data.get("alias")
        device_id = data.get("device_id")
        
        if not alias or not device_id:
            emit('error', {"message": "Missing alias or device_id"})
            return
        
        if hybrid_orchestrator:
            success = hybrid_orchestrator.teach_alias(alias, device_id)
            emit('alias_taught', {
                "success": success,
                "alias": alias,
                "device_id": device_id
            })
        else:
            emit('error', {"message": "Orchestrator not available"})


# Event bus listeners - broadcast to all clients
def _on_agent_response(event):
    """Broadcast agent response to all connected clients."""
    if socketio:
        payload = event.get("payload", {})
        socketio.emit('command_result', {
            "success": True,
            "message": payload.get("text", "Done"),
            "source": payload.get("source", "unknown")
        })


def _on_tool_calls(event):
    """Broadcast tool calls to all connected clients."""
    if socketio:
        payload = event.get("payload", [])
        socketio.emit('tool_calls', {
            "calls": payload,
            "source": event.get("source", "unknown"),
            "timestamp": event.get("timestamp", time.time())
        })


def _on_device_state_changed(event):
    """Broadcast device state changes to all clients."""
    if socketio:
        payload = event.get("payload", {})
        socketio.emit('device_state_update', payload)


def get_connected_clients():
    """Get list of connected clients."""
    return connected_clients


def broadcast_message(event_type: str, data: Dict[str, Any]):
    """Broadcast a message to all connected clients."""
    if socketio:
        socketio.emit(event_type, data)
