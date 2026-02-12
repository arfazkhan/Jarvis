from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/recommendations")
async def get_recommendations(sys: SystemContainer = Depends(get_system_state)):
    """Get active advisory recommendations."""
    if not sys.llm_agent or not hasattr(sys.llm_agent, "advisor"):
        return []

    # Access advisor from LLMAgent
    # Note: In real impl, advisor might be standalone service
    # For now, we return mock data or real data if available
    return []

@router.get("/trust/metrics")
async def get_trust_metrics(sys: SystemContainer = Depends(get_system_state)):
    """Get trust calibration metrics."""
    # Placeholder for TrustCalibrator
    return {
        "global_trust_score": 0.85,
        "operator_agreement": 0.92,
        "hallucination_rate": 0.03
    }

@router.get("/audit-log")
async def get_audit_log(sys: SystemContainer = Depends(get_system_state)):
    """Get decision audit log."""
    return []
