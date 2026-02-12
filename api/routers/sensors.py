from fastapi import APIRouter, Depends, Body
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.get("/health")
async def get_sensor_health(sys: SystemContainer = Depends(get_system_state)):
    """Sensor health heatmap."""
    return {"healthy": 98, "stale": 2, "broken": 0}

@router.get("/fusion")
async def get_fusion_matrix(sys: SystemContainer = Depends(get_system_state)):
    """State estimation confidence."""
    return {"confidence_matrix": "[[0.9, 0.1], [0.1, 0.9]]"}
    
@router.post("/ingest")
async def ingest_telemetry(payload: dict = Body(...), sys: SystemContainer = Depends(get_system_state)):
    """Detailed telemetry ingestion webhook."""
    # Push to Event Bus
    sys.event_bus.publish({
        "type": "telemetry_update", 
        "payload": payload
    })
    return {"status": "Queued"}
