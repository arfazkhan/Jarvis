from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/dashboard")
async def get_dashboard(sys: SystemContainer = Depends(get_system_state)):
    """High-level system dashboard."""
    state = {}
    if sys.state_engine:
        state = sys.state_engine.summary()
    
    return {
        "status": "HEALTHY",
        "active_alarms": 0, # Placeholder
        "efficiency_score": 92.5,
        "equipment_online": len(state.get("devices", {})),
        "gsas_rating": "Gold"
    }

@router.get("/equipment")
async def list_equipment(sys: SystemContainer = Depends(get_system_state)):
    """List all equipment."""
    if not sys.state_engine: 
        return []
    return sys.state_engine.state.get("devices", {})

@router.get("/equipment/{device_id}")
async def get_equipment(device_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Get specific device details."""
    devices = sys.state_engine.state.get("devices", {})
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    return devices[device_id]

@router.get("/alarms")
async def get_alarms(sys: SystemContainer = Depends(get_system_state)):
    """Get active alarms."""
    # Placeholder: In real implementation, query AlarmManager
    return []
