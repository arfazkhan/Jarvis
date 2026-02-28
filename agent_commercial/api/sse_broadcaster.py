import asyncio
import logging
from typing import Dict, Any, List, AsyncGenerator
import json

logger = logging.getLogger("arvis.api.sse")

class SSEBroadcaster:
    """
    Singleton Event Bus for Server-Sent Events (Glass Box API).
    Broadcasts simulation thoughts, plans, and tool execution to UI.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._queues = []
            cls._instance._loops = {} # queue_id -> loop
        return cls._instance

    def __init__(self):
        # Already initialized in __new__
        pass

    async def broadcast(self, event_type: str, data: Any):
        """
        Send an event to all connected clients.
        
        Args:
            event_type: 'thought', 'plan', 'tool_use', 'learning', 'sim_status'
            data: JSON-serializable payload
        """
        if not self._queues:
            return

        message = {
            "event": event_type,
            "data": json.dumps(data)
        }
        
        # Fan out to all queues
        dead_queues = []
        for q_id, q in self._queues:
            loop = self._loops.get(q_id)
            if not loop:
                dead_queues.append((q_id, q))
                continue
                
            try:
                # Use call_soon_threadsafe to push to queues that might be in other event loops (API Thread)
                loop.call_soon_threadsafe(q.put_nowait, message)
            except Exception as e:
                logger.warning(f"Failed to push to SSE queue: {e}")
                dead_queues.append((q_id, q))
        
        # Cleanup dead connections
        for dq in dead_queues:
            if dq in self._queues:
                self._queues.remove(dq)
                self._loops.pop(dq[0], None)

    async def subscribe(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Yields events for a single client connection.
        """
        import uuid
        q_id = str(uuid.uuid4())
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        self._queues.append((q_id, queue))
        self._loops[q_id] = loop
        
        try:
            while True:
                message = await queue.get()
                yield message
        except asyncio.CancelledError:
            self._queues = [item for item in self._queues if item[0] != q_id]
            self._loops.pop(q_id, None)
            raise
