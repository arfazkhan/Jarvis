from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/history")
async def get_conversation_history(sys: SystemContainer = Depends(get_system_state)):
    """Get active session history."""
    if sys.dialogue_manager:
        return sys.dialogue_manager.history
    return []

@router.post("/intent/check")
async def check_intent(text: str, sys: SystemContainer = Depends(get_system_state)):
    """Test NLU classification."""
    if not sys.dialogue_manager:
        raise HTTPException(status_code=503, detail="Dialogue Manager offline")
    
    return sys.dialogue_manager.classifier.classify(text)

@router.delete("/session")
async def reset_session(sys: SystemContainer = Depends(get_system_state)):
    """Reset conversation state."""
    if sys.dialogue_manager:
        sys.dialogue_manager.history = []
        return {"status": "Session Reset"}
    return {"status": "No Active Session"}
