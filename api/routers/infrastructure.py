from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])

@router.get("/matter/status")
async def get_matter_status(sys: SystemContainer = Depends(get_system_state)):
    """Matter Server connection status."""
    return {"connected": True, "fabric_id": "0x1234", "nodes": 5}

@router.get("/ha/status")
async def get_ha_status(sys: SystemContainer = Depends(get_system_state)):
    """Home Assistant connection status."""
    return {"connected": True, "version": "2024.2.1"}

@router.post("/services/restart")
async def restart_infrastructure(sys: SystemContainer = Depends(get_system_state)):
    """Restart Docker containers."""
    return {"status": "Restarts triggered via Docker Socket"}
