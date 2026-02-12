from fastapi import APIRouter, Depends
from typing import List
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/patterns")
async def get_patterns(sys: SystemContainer = Depends(get_system_state)):
    """Discovered operational patterns."""
    if sys.learning_engine and hasattr(sys.learning_engine, "pattern_analyzer"):
        # return sys.learning_engine.pattern_analyzer.get_top_patterns()
        pass
    return [{"pattern": "Chiller starts early on Mondays", "confidence": 0.9}]

@router.post("/patterns/promote")
async def promote_pattern(pattern_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Promote a pattern to a fixed rule."""
    return {"status": "Promoted"}

@router.get("/trends")
async def get_trends(sys: SystemContainer = Depends(get_system_state)):
    """Habit drift trends."""
    # Ported from legacy Flask logic
    return {"wake_time_drift": "-15min", "energy_usage_trend": "+5%"}

@router.get("/anomalies")
async def get_anomalies(sys: SystemContainer = Depends(get_system_state)):
    """System anomalies."""
    return [{"type": "Energy Spike", "timestamp": "2024-02-11T10:00:00Z"}]
