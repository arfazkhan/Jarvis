from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/goals")
async def get_active_goals(sys: SystemContainer = Depends(get_system_state)):
    """Get active agent goals."""
    if not sys.mission_manager:
        return []
        
    active_ids = sys.mission_manager.list_active_missions()
    goals = []
    for mid in active_ids:
        status = sys.mission_manager.get_status(mid)
        goals.append(status)
    return goals

@router.get("/plan/active")
async def get_active_plan(sys: SystemContainer = Depends(get_system_state)):
    """Get currently executing plan."""
    if not sys.planning_flow:
        return None
        
    return sys.planning_flow.get_current_plan()

@router.post("/inference")
async def infer_intent(cmd: str, sys: SystemContainer = Depends(get_system_state)):
    """Infer intent from vague command."""
    if not sys.mission_manager:
        return {"error": "Mission Manager offline"}
        
    # Placeholder: connect to MissionInference module
    return {"intent": "unknown", "confidence": 0.0}
    
@router.get("/templates")
async def list_templates(sys: SystemContainer = Depends(get_system_state)):
    """List available mission templates."""
    # Placeholder
    return ["energy_audit", "daily_briefing", "security_patrol"]
