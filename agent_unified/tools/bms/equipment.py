from typing import Optional, List, Any
from agent_unified.tools.base import BaseTool, ToolResult

class GetEquipmentStatus(BaseTool):
    """Get status of BMS equipment"""
    
    name: str = "get_equipment_status"
    description: str = "Get current status of a specific piece of BMS equipment including operational state, data points, and alarms."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "Equipment identifier (e.g., 'AHU-01', 'CH-01')"
            }
        },
        "required": ["equipment_id"]
    }
    
    # Injected engine
    bms_state: Optional[Any] = None
    
    async def execute(self, equipment_id: str) -> ToolResult:
        if not self.bms_state:
            return self.fail_response("BMS state engine not available")
        
        try:
            # 1. Try to get equipment object
            equipment = self.bms_state.get_equipment(equipment_id)
            if not equipment:
                return self.fail_response(f"Equipment {equipment_id} not found")
            
            # 2. Get data points
            points = self.bms_state.get_points_by_equipment(equipment_id)
            
            # 3. Get alarms (if available via state or separate engine)
            alarms = []
            if hasattr(self.bms_state, 'get_alarms_by_equipment'):
                alarms = self.bms_state.get_alarms_by_equipment(equipment_id)
            
            result = {
                "id": equipment_id,
                "name": equipment.name,
                "type": equipment.eq_type.value if hasattr(equipment.eq_type, 'value') else str(equipment.eq_type),
                "status": equipment.status.value if hasattr(equipment.status, 'value') else str(equipment.status),
                "location": equipment.location,
                "points": [
                    {"id": p.point_id, "name": p.name, "value": p.value, "unit": p.unit} 
                    for p in points
                ],
                "active_alarms": len(alarms)
            }
            
            return self.success_response(result)
            
        except Exception as e:
            return self.fail_response(f"Error getting equipment status: {str(e)}")

class ListEquipment(BaseTool):
    """List BMS equipment"""
    name: str = "list_equipment"
    description: str = "List all BMS equipment, optionally filtered."
    parameters: dict = {
        "type": "object",
        "properties": {
            "equipment_type": {"type": "string", "description": "Filter by type (ahu, chiller, etc)"},
            "status": {"type": "string", "description": "Filter by status (running, fault)"}
        }
    }
    
    bms_state: Optional[Any] = None
    
    async def execute(self, equipment_type: str = None, status: str = None) -> ToolResult:
        if not self.bms_state:
            return self.fail_response("BMS state engine not available")
            
        all_eq = self.bms_state.get_all_equipment()
        filtered = []
        
        for eq in all_eq:
            match = True
            if equipment_type and equipment_type.lower() not in str(eq.eq_type).lower():
                match = False
            if status and status.lower() not in str(eq.status).lower():
                match = False
            if match:
                filtered.append(eq.equipment_id)
                
        return self.success_response({"count": len(filtered), "equipment_ids": filtered[:50]})
