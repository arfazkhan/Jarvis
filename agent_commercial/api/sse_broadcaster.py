import asyncio
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional
import json
from datetime import datetime

logger = logging.getLogger("arvis.api.sse")

class SSEBroadcaster:
    """
    Channel-based Singleton Event Bus for Server-Sent Events (Glass Box API).
    
    Supports two isolated channels:
      - "chat"    : Events from the interactive chat swarm (task_list, tool_use, thought)
      - "monitor" : Events from the background demo orchestrator (telemetry, ambient thoughts, advisories)
    
    Subscribers choose which channel to listen on. Events broadcast to one channel
    are never delivered to subscribers of the other channel.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._channel_queues: Dict[str, List] = {
                "chat": [],
                "monitor": [],
            }
            cls._instance._loops: Dict[str, Any] = {}
        return cls._instance

    def __init__(self):
        pass

    async def broadcast(self, event_type: str, data: Any, channel: str = "monitor"):
        """
        Send an event to all subscribers on a specific channel.
        
        Args:
            event_type: 'thought', 'tool_use', 'task_list', 'telemetry', 'swarm_event', etc.
            data: JSON-serializable payload
            channel: 'chat' or 'monitor' (default: 'monitor')
        """
        queues = self._channel_queues.get(channel, [])
        if not queues:
            return

        # --- Inject User-Friendly Formatting ---
        try:
            from agent_commercial.api.formatters import format_agent_name, format_tool_name
            if isinstance(data, dict):
                if event_type == "thought" and "node" in data:
                    data["node"] = format_agent_name(data["node"])
                elif event_type == "tool_use" and "tool" in data:
                    data["tool"] = format_tool_name(data["tool"])
                elif event_type == "task_list" and "tasks" in data:
                    for t in data["tasks"]:
                        if "task" in t:
                            for raw_node in ["Energy_Agent", "Comfort_Agent", "Strategic_Agent", "Alarm_Agent", "Maintenance_Agent", "Memory_Agent", "Fast_Router"]:
                                if raw_node in t["task"]:
                                    t["task"] = t["task"].replace(raw_node, format_agent_name(raw_node))
        except ImportError:
            pass

        message = {
            "event": event_type,
            "data": json.dumps(data)
        }
        
        dead_queues = []
        for q_id, q in queues:
            loop = self._loops.get(q_id)
            if not loop:
                dead_queues.append((q_id, q))
                continue
                
            try:
                loop.call_soon_threadsafe(q.put_nowait, message)
            except Exception as e:
                logger.warning(f"Failed to push to SSE queue [{channel}]: {e}")
                dead_queues.append((q_id, q))
        
        for dq in dead_queues:
            if dq in queues:
                queues.remove(dq)
                self._loops.pop(dq[0], None)

    async def broadcast_plan_update(self, plan, channel: str = "chat"):
        """
        P4: Broadcast live investigation plan state to operator.
        Replaces fixed 4-phase tasks_state with dynamic plan.tasks rendering.
        """
        if plan is None:
            return

        tasks_data = []
        for t in plan.tasks:
            status_map = {
                "pending": "pending",
                "active": "in_progress",
                "complete": "completed",
                "failed": "error",
                "skipped": "skipped",
            }
            tasks_data.append({
                "id": t.id,
                "task": t.goal,
                "status": status_map.get(t.status.value, "pending"),
                "has_evidence": t.has_evidence,
            })

        payload = {
            "plan_id": plan.id,
            "progress": round(plan.progress * 100),
            "coverage": round(plan.coverage * 100),
            "budget": plan.budget.to_dict(),
            "tasks": tasks_data,
        }

        # M7.4: Append ml_health when ML evidence is present in the plan
        try:
            all_ev = plan.evidence.get_all()
            ml_ev = [e for e in all_ev if getattr(e, "model_id", None) or getattr(e, "is_ml_fallback", False)]
            if ml_ev:
                from agent_commercial.ml.observability import get_ml_observability
                obs = get_ml_observability()
                ml_health = {}
                for ev in ml_ev:
                    mid = getattr(ev, "model_id", None) or ev.source_tool
                    if mid and mid not in ml_health:
                        ml_health[mid] = obs.get_model_health(mid)
                if ml_health:
                    payload["ml_health"] = ml_health
        except Exception:
            pass

        await self.broadcast("plan_update", payload, channel=channel)

    async def subscribe(self, channel: str = "monitor") -> AsyncGenerator[Dict[str, Any], None]:
        """
        Yields events for a single client connection on a specific channel.
        
        Args:
            channel: 'chat' or 'monitor'
        """
        import uuid
        q_id = str(uuid.uuid4())
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        if channel not in self._channel_queues:
            self._channel_queues[channel] = []
        
        self._channel_queues[channel].append((q_id, queue))
        self._loops[q_id] = loop
        
        try:
            yield {"event": "system", "data": json.dumps({"message": f"SSE Stream Connected (channel: {channel})"})}
            
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield message
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": json.dumps({"timestamp": str(datetime.now())})}
        except asyncio.CancelledError:
            self._channel_queues[channel] = [item for item in self._channel_queues[channel] if item[0] != q_id]
            self._loops.pop(q_id, None)
            raise
        except Exception as e:
            logger.error(f"SSE Subscribe Error [{channel}]: {e}")
            self._channel_queues[channel] = [item for item in self._channel_queues[channel] if item[0] != q_id]
            self._loops.pop(q_id, None)
