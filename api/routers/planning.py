from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/active")
async def get_active_plan(sys: SystemContainer = Depends(get_system_state)):
    """Current execution plan."""
    if sys.planning_flow:
        return sys.planning_flow.get_current_plan()
    return None

@router.get("/results")
async def get_plan_results(sys: SystemContainer = Depends(get_system_state)):
    """Execution history."""
    if sys.planning_flow:
        return sys.planning_flow.get_execution_results()
    return []

@router.post("/create")
async def create_plan(request: str, sys: SystemContainer = Depends(get_system_state)):
    """Trigger manual plan generation."""
    if sys.planning_flow:
        # Async execution needed
        # For now, just a placeholder
        return {"status": "Async execution not yet exposed via HTTP"}
    return {"error": "Planning Flow offline"}
