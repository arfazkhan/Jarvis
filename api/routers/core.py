from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/arbitration")
async def get_arbitration_status(sys: SystemContainer = Depends(get_system_state)):
    """Conflict resolution status."""
    # Placeholder for ArbitrationManager
    return {"active_conflicts": 0, "resolution_strategy": "priority_based"}

@router.get("/feedback/loops")
async def get_feedback_loops(sys: SystemContainer = Depends(get_system_state)):
    """Feedback loop health."""
    return {
        "perception_loop": "healthy",
        "action_loop": "healthy",
        "learning_loop": "idle"
    }

@router.get("/bus/events")
async def stream_events(sys: SystemContainer = Depends(get_system_state)):
    """Stream events (SSE placeholder)."""
    return {"status": "Use WebSocket /ws for real-time events"}
