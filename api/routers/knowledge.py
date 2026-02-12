from fastapi import APIRouter, Depends
from typing import List
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/skills/search")
async def search_skills(query: str, sys: SystemContainer = Depends(get_system_state)):
    """Search institutional memory."""
    # Placeholder for RAG search
    return []

@router.post("/simulation/what-if")
async def run_simulation(sys: SystemContainer = Depends(get_system_state)):
    """Run Gaussian Process simulation."""
    return {"status": "Simulation queued"}

@router.get("/occupancy/ghosts")
async def detect_ghosts(sys: SystemContainer = Depends(get_system_state)):
    """Detect empty-but-cooled spaces."""
    return []
