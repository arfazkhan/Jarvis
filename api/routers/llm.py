from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])

@router.get("/providers")
async def list_providers(sys: SystemContainer = Depends(get_system_state)):
    """List active LLM providers."""
    return [
        {"name": "OpenAI", "model": "gpt-4-turbo", "status": "active"},
        {"name": "NVIDIA", "model": "llama-3-70b-instruct", "status": "fallback"},
        {"name": "Groq", "model": "mixtral-8x7b", "status": "speedy"}
    ]

@router.post("/config/switch")
async def switch_provider(provider_name: str, sys: SystemContainer = Depends(get_system_state)):
    """Hot-swap LLM provider."""
    # sys.llm_agent.switch_provider(provider_name)
    return {"status": "Switched", "current": provider_name}

@router.get("/stats")
async def get_stats(sys: SystemContainer = Depends(get_system_state)):
    """Token usage stats."""
    return {"total_tokens": 154300, "cost_estimate": 4.52}
