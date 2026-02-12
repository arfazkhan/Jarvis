from fastapi import APIRouter, Depends
from typing import Dict, Any
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/state")
async def get_emotional_state(sys: SystemContainer = Depends(get_system_state)):
    """Current emotional baseline."""
    # Placeholder: connect to PersonalityManager
    return {"mood": "Focused", "arousal": 0.6, "dominance": 0.7}

@router.post("/persona")
async def switch_persona(persona_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Switch active persona."""
    return {"status": "Switched", "current": persona_id}
