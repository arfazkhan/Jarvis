"""
BMS Alarm Tools
===============

Class-based tools for alarm management and analysis.
"""

from typing import Any, Optional, List
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class GetActiveAlarms(BaseTool):
    """Get all active alarms in the building."""
    
    name: str = "get_active_alarms"
    description: str = "Get all active alarms in the building, sorted by priority. Returns alarm details, severity, duration, and suggested actions."
    parameters: dict = {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "description": "Filter by severity: critical, high, medium, low",
                "enum": ["critical", "high", "medium", "low"]
            },
            "equipment_id": {
                "type": "string",
                "description": "Filter by specific equipment"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of alarms to return (default: 20)",
                "default": 20
            }
        },
        "required": []
    }
    
    alarm_engine: Optional[Any] = None
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        severity: Optional[str] = None,
        equipment_id: Optional[str] = None,
        limit: int = 20
    ) -> ToolResult:
        engine = self.alarm_engine or self.bms_state
        if not engine:
            return self.fail_response("Alarm engine not available")
        
        try:
            # Get active alarms
            if hasattr(engine, 'get_active_alarms'):
                alarms = engine.get_active_alarms()
            else:
                alarms = []
            
            # Apply filters
            if severity:
                alarms = [
                    a for a in alarms 
                    if (a.severity.value if hasattr(a.severity, 'value') else str(a.severity)).lower() == severity.lower()
                ]
            
            if equipment_id:
                alarms = [
                    a for a in alarms 
                    if hasattr(a, 'equipment_id') and a.equipment_id == equipment_id
                ]
            
            # Sort by severity (critical first)
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            alarms = sorted(alarms, key=lambda a: severity_order.get(
                (a.severity.value if hasattr(a.severity, 'value') else str(a.severity)).lower(), 4
            ))
            
            result = {
                "total_active": len(alarms),
                "alarms": [
                    {
                        "alarm_id": a.alarm_id,
                        "equipment_id": getattr(a, 'equipment_id', None),
                        "message": a.message,
                        "severity": a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
                        "state": a.state.value if hasattr(a.state, 'value') else str(a.state),
                        "triggered_at": str(a.triggered_at) if hasattr(a, 'triggered_at') else None
                    }
                    for a in alarms[:limit]
                ]
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error getting alarms: {str(e)}")


class ExplainAlarm(BaseTool):
    """Get detailed explanation for a specific alarm."""
    
    name: str = "explain_alarm"
    description: str = "Get detailed explanation and root cause analysis for a specific alarm, including related alarms and recommended actions."
    parameters: dict = {
        "type": "object",
        "properties": {
            "alarm_id": {
                "type": "string",
                "description": "The alarm identifier"
            }
        },
        "required": ["alarm_id"]
    }
    
    alarm_engine: Optional[Any] = None
    bms_state: Optional[Any] = None
    skillbook: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, alarm_id: str) -> ToolResult:
        engine = self.alarm_engine or self.bms_state
        if not engine:
            return self.fail_response("Alarm engine not available")
        
        try:
            # Get the alarm
            alarm = None
            if hasattr(engine, 'get_active_alarms'):
                for a in engine.get_active_alarms():
                    if a.alarm_id == alarm_id:
                        alarm = a
                        break
            
            if not alarm:
                return self.fail_response(f"Alarm '{alarm_id}' not found")
            
            # Build explanation
            explanation = {
                "alarm_id": alarm_id,
                "message": alarm.message,
                "severity": alarm.severity.value if hasattr(alarm.severity, 'value') else str(alarm.severity),
                "equipment_id": getattr(alarm, 'equipment_id', None),
                "analysis": {
                    "probable_cause": f"Abnormal condition detected on {getattr(alarm, 'equipment_id', 'equipment')}",
                    "impact": "May affect system performance if not addressed",
                    "recommended_actions": [
                        "Verify sensor readings",
                        "Check equipment status",
                        "Review recent changes"
                    ]
                }
            }
            
            # Check skillbook for related knowledge
            if self.skillbook and hasattr(alarm, 'equipment_id'):
                try:
                    skills = self.skillbook.query_skills(
                        equipment_id=alarm.equipment_id,
                        limit=3
                    )
                    if skills:
                        explanation["historical_knowledge"] = [
                            {"title": s.title, "description": s.description[:200]}
                            for s in skills[:2]
                        ]
                except Exception:
                    pass
            
            return self.success_response(explanation)
            
        except Exception as e:
            return self.fail_response(f"Error explaining alarm: {str(e)}")


class AcknowledgeAlarm(BaseTool):
    """Acknowledge an alarm."""
    
    name: str = "acknowledge_alarm"
    description: str = "Acknowledge an alarm to indicate it has been seen and is being addressed."
    parameters: dict = {
        "type": "object",
        "properties": {
            "alarm_id": {
                "type": "string",
                "description": "The alarm identifier"
            },
            "note": {
                "type": "string",
                "description": "Optional note about the acknowledgment"
            }
        },
        "required": ["alarm_id"]
    }
    
    alarm_engine: Optional[Any] = None
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, alarm_id: str, note: Optional[str] = None) -> ToolResult:
        engine = self.alarm_engine or self.bms_state
        if not engine:
            return self.fail_response("Alarm engine not available")
        
        try:
            if hasattr(engine, 'acknowledge_alarm'):
                engine.acknowledge_alarm(alarm_id, by="ARVIS")
                
                result = {
                    "alarm_id": alarm_id,
                    "status": "acknowledged",
                    "acknowledged_by": "ARVIS",
                    "note": note or "Acknowledged via ARVIS Ops Copilot"
                }
                
                return self.success_response(result)
            else:
                return self.fail_response("Alarm acknowledgment not supported")
            
        except Exception as e:
            return self.fail_response(f"Error acknowledging alarm: {str(e)}")
