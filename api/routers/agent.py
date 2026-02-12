from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, List, Any

from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

# Models
class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    voice_mode: bool = False

class ChatResponse(BaseModel):
    response: str
    tool_calls: List[Dict[str, Any]] = []
    confidence: float = 1.0

class InstructionRequest(BaseModel):
    command: str
    priority: str = "normal"

# Endpoints

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, sys: SystemContainer = Depends(get_system_state)):
    """Main interaction endpoint for the Agent."""
    if not sys.llm_agent:
        raise HTTPException(status_code=503, detail="Agent Brain not initialized")
    
    # Construct event for the Event Bus
    event = {
        "type": "user_message",
        "payload": {
            "text": req.message,
            "context": req.context or {},
            "source": "api"
        }
    }
    
    # Streaming handling is complex in HTTP, using sync wait for v1
    # TODO: Implement true async streaming response or SSE
    try:
        response_generator = sys.llm_agent.handle_streaming(event)
        
        full_text = []
        for token in response_generator:
            full_text.append(token)
            
        return ChatResponse(
            response="".join(full_text),
            tool_calls=[] # We need to capture these from the agent logic
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/instruct")
async def instruct(req: InstructionRequest, sys: SystemContainer = Depends(get_system_state)):
    """Direct instruction execution."""
    if not sys.tool_executor:
        raise HTTPException(status_code=503, detail="Tool Executor not ready")
        
    # Execute direct command via Tool Executor or LLM planning
    # For now, treat as high-priority chat
    return await chat(ChatRequest(message=f"EXECUTE: {req.command}"), sys)

@router.get("/briefing")
async def get_briefing(sys: SystemContainer = Depends(get_system_state)):
    """Generate daily briefing."""
    # Placeholder for Briefing Generation Logic
    # In V2, call sys.briefing_engine.generate()
    return {
        "summary": "System operating normally. Efficiency at 94%.",
        "alerts": [],
        "suggestions": ["Optimize Chiller Setpoint (+2%)"]
    }

@router.get("/history")
async def get_history(sys: SystemContainer = Depends(get_system_state)):
    """Get Agent interaction history."""
    if sys.state_engine:
        return sys.state_engine.get_history(limit=50)
    return []
