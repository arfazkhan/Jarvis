"""
BMS Equipment Tools
===================

Class-based tools for equipment status and management.
"""

from typing import Any, Optional, List
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class GetEquipmentStatus(BaseTool):
    """Get BMS equipment status including operational state and data points."""
    
    name: str = "get_equipment_status"
    description: str = "Get the current status of a specific piece of BMS equipment including its operational state, data points, and active alarms."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "The equipment identifier (e.g., 'AHU-01', 'CH-01')"
            }
        },
        "required": ["equipment_id"]
    }
    
    # Injected BMS engines
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, equipment_id: str) -> ToolResult:
        if not self.bms_state:
            return self.fail_response("BMS state engine not available")
        
        try:
            equipment = self.bms_state.get_equipment_sync(equipment_id)
            if not equipment:
                return self.fail_response(f"Equipment '{equipment_id}' not found")
            
            # Get data points and alarms
            points = self.bms_state.get_points_by_equipment(equipment_id)
            alarms = self.bms_state.get_alarms_by_equipment(equipment_id)
            
            result = {
                "equipment_id": equipment_id,
                "name": equipment.name,
                "type": equipment.eq_type.value if hasattr(equipment.eq_type, 'value') else str(equipment.eq_type),
                "status": equipment.status.value if hasattr(equipment.status, 'value') else str(equipment.status),
                "location": equipment.location,
                "data_points": [
                    {
                        "id": p.point_id,
                        "name": getattr(p, 'name', p.point_id),
                        "value": p.value,
                        "unit": getattr(p, 'unit', '')
                    }
                    for p in (points[:12] if points else [])
                ],
                "active_alarms": [
                    {
                        "id": a.alarm_id,
                        "message": a.message,
                        "severity": a.severity.value if hasattr(a.severity, 'value') else str(a.severity)
                    }
                    for a in (alarms[:5] if alarms else [])
                    if hasattr(a, 'state') and a.state.value == "active"
                ]
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error getting equipment status: {str(e)}")


class ListEquipment(BaseTool):
    """List all BMS equipment with optional filters."""
    
    name: str = "list_equipment"
    description: str = "List all BMS equipment, optionally filtered by type, status, or location."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_type": {
                "type": "string",
                "description": "Filter by type: air_handling_unit, chiller, vav, fcu, pump, etc.",
                "enum": ["air_handling_unit", "chiller", "vav", "fcu", "pump", "boiler", "cooling_tower"]
            },
            "status": {
                "type": "string",
                "description": "Filter by status: running, stopped, fault, maintenance",
                "enum": ["running", "stopped", "fault", "maintenance", "offline"]
            },
            "location": {
                "type": "string",
                "description": "Filter by location (building, floor, zone)"
            }
        },
        "required": []
    }
    
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self, 
        equipment_type: Optional[str] = None,
        status: Optional[str] = None,
        location: Optional[str] = None
    ) -> ToolResult:
        if not self.bms_state:
            return self.fail_response("BMS state engine not available")
        
        try:
            equipment_list = self.bms_state.get_all_equipment()
            
            # Apply filters
            if equipment_type:
                equipment_list = [
                    e for e in equipment_list 
                    if (e.eq_type.value if hasattr(e.eq_type, 'value') else str(e.eq_type)) == equipment_type
                ]
            
            if status:
                equipment_list = [
                    e for e in equipment_list 
                    if (e.status.value if hasattr(e.status, 'value') else str(e.status)) == status
                ]
            
            if location:
                equipment_list = [
                    e for e in equipment_list 
                    if location.lower() in (e.location or "").lower()
                ]
            
            result = {
                "total_count": len(equipment_list),
                "equipment": [
                    {
                        "id": e.equipment_id,
                        "name": e.name,
                        "type": e.eq_type.value if hasattr(e.eq_type, 'value') else str(e.eq_type),
                        "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
                        "location": e.location
                    }
                    for e in equipment_list[:50]  # Limit results
                ]
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error listing equipment: {str(e)}")


class GetEquipmentHealth(BaseTool):
    """Get detailed health analysis for equipment."""
    
    name: str = "get_equipment_health"
    description: str = "Get detailed health analysis for specific equipment including health score, trending, and risk factors."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "The equipment identifier"
            }
        },
        "required": ["equipment_id"]
    }
    
    bms_state: Optional[Any] = None
    ml_engine: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, equipment_id: str) -> ToolResult:
        if not self.bms_state:
            return self.fail_response("BMS state engine not available")
        
        try:
            equipment = self.bms_state.get_equipment_sync(equipment_id)
            if not equipment:
                return self.fail_response(f"Equipment '{equipment_id}' not found")
            
            # Calculate health score (simplified - could use ML engine)
            health_score = 85  # Default good health
            risk_factors = []
            
            # Check for recent alarms
            alarms = self.bms_state.get_alarms_by_equipment(equipment_id)
            active_alarms = [a for a in (alarms or []) if hasattr(a, 'state') and a.state.value == "active"]
            
            if len(active_alarms) > 0:
                health_score -= len(active_alarms) * 10
                risk_factors.append(f"{len(active_alarms)} active alarm(s)")
            
            # Check equipment status
            if hasattr(equipment, 'status'):
                status_val = equipment.status.value if hasattr(equipment.status, 'value') else str(equipment.status)
                if status_val == "fault":
                    health_score -= 30
                    risk_factors.append("Equipment in fault state")
                elif status_val == "maintenance":
                    risk_factors.append("Currently under maintenance")
            
            result = {
                "equipment_id": equipment_id,
                "name": equipment.name,
                "health_score": max(0, min(100, health_score)),
                "health_status": "good" if health_score >= 80 else ("fair" if health_score >= 60 else "poor"),
                "risk_factors": risk_factors,
                "recommendation": "Monitor closely" if health_score < 80 else "Normal operation"
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error getting equipment health: {str(e)}")
