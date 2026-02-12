from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/cost/burn-rate")
async def get_burn_rate(sys: SystemContainer = Depends(get_system_state)):
    """Real-time financial burn rate."""
    return {"burn_rate_qar_per_hour": 45.2, "trend": "Stable"}

@router.get("/gsas/status")
async def get_gsas_status(sys: SystemContainer = Depends(get_system_state)):
    """GSAS Sustainability Score."""
    return {"score": 2.8, "level": "Gold", "next_target": "Platinum"}

@router.get("/analysis")
async def get_energy_analysis(sys: SystemContainer = Depends(get_system_state)):
    """Deep energy breakdown."""
    return {"chiller_plant": "65%", "lighting": "15%", "other": "20%"}
