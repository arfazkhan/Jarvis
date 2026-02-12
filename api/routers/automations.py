from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/jobs")
async def list_jobs(sys: SystemContainer = Depends(get_system_state)):
    """List scheduled automation jobs."""
    if sys.automation_engine:
        return sys.automation_engine.list()
    return []

@router.post("/jobs/trigger")
async def trigger_job(job_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Manually trigger a job."""
    return {"status": "Triggered"}

@router.post("/scenes/activate")
async def activate_scene(scene_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Activate a lighting/HVAC scene."""
    # Placeholder for SceneEngine
    return {"status": "Active", "scene": scene_id}
