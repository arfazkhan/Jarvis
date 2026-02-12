from typing import Optional, Any
from agent_unified.tools.base import BaseTool, ToolResult

class GetActiveAlarms(BaseTool):
    """Get active alarms"""
    name: str = "get_active_alarms"
    description: str = "Get all active BMS alarms sorted by priority."
    parameters: dict = {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]}
        }
    }
    
    alarm_engine: Optional[Any] = None
    
    async def execute(self, priority: str = None) -> ToolResult:
        if not self.alarm_engine:
            return self.fail_response("Alarm engine not available")
            
        alarms = self.alarm_engine.get_active_alarms(priority_filter=priority)
        return self.success_response([a.to_dict() for a in alarms[:20]])

class AcknowledgeAlarm(BaseTool):
    """Acknowledge an alarm"""
    name: str = "acknowledge_alarm"
    description: str = "Acknowledge a specific alarm."
    parameters: dict = {
        "type": "object",
        "properties": {
            "alarm_id": {"type": "string"},
            "note": {"type": "string"}
        },
        "required": ["alarm_id"]
    }
    
    alarm_engine: Optional[Any] = None
    
    async def execute(self, alarm_id: str, note: str = "") -> ToolResult:
        if not self.alarm_engine:
            return self.fail_response("Alarm engine not available")
            
        success = self.alarm_engine.acknowledge_alarm(alarm_id, "ARVIS", note)
        return self.success_response({"status": "acknowledged" if success else "failed"})
