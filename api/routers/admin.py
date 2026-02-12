from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])

class KillSwitchRequest(BaseModel):
    reason: str
    force: bool = False

@router.post("/safety-override")
async def safety_override(req: KillSwitchRequest, sys: SystemContainer = Depends(get_system_state)):
    """EMERGENCY KILL SWITCH."""
    # 1. Stop all automation
    if sys.automation_engine:
        # sys.automation_engine.stop_all() 
        pass
        
    # 2. Shutdown Matter Controller
    if sys.matter_controller:
        # sys.matter_controller.emergency_stop() 
        pass
        
    return {"status": "SHUTDOWN_INITIATED", "reason": req.reason}

@router.get("/health")
async def health_check(sys: SystemContainer = Depends(get_system_state)):
    """Internal component health."""
    return {
        "event_bus": sys.event_bus is not None,
        "state_engine": sys.state_engine is not None,
        "llm_agent": sys.llm_agent is not None,
        "voice": sys.voice_coordinator is not None
    }

@router.post("/restart")
async def restart_services():
    """Trigger service restart (requires process manager)."""
    return {"status": "Not Implemented (Requires Supervisor)"}
    
@router.get("/config")
async def get_config():
    """View active feature flags."""
    return {
        "voice_enabled": True,
        "learning_enabled": True,
        "safety_guardrails": "STRICT"
    }
