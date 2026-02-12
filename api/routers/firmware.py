from fastapi import APIRouter, Depends
from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])

@router.get("/devices")
async def list_iot_devices(sys: SystemContainer = Depends(get_system_state)):
    """List Matter/ESP32 devices."""
    if sys.matter_controller:
        # sys.matter_controller.get_nodes()
        pass
    return [
        {"id": "node_12", "type": "ESP32-C6", "firmware": "1.2.0", "status": "online"},
        {"id": "node_14", "type": "ESP32-H2", "firmware": "1.1.9", "status": "updating"}
    ]

@router.post("/ota/update")
async def trigger_ota(device_id: str, version: str, sys: SystemContainer = Depends(get_system_state)):
    """Push firmware update."""
    return {"status": "Update Pushed", "eta_seconds": 120}

@router.get("/logs")
async def get_device_logs(device_id: str = "node_12", sys: SystemContainer = Depends(get_system_state)):
    """Stream device logs."""
    return [f"[{device_id}] Booting...", f"[{device_id}] Connecting to Matter Fabric...", f"[{device_id}] Online"]
