from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])
logger = logging.getLogger("arvis.api.firmware")

# Global OTA manager instance
_ota_manager = None


def get_ota_manager():
    """Get or create OTA manager instance"""
    global _ota_manager
    if _ota_manager is None:
        from agent_home.firmware.ota_manager import OTAManager
        _ota_manager = OTAManager()
    return _ota_manager


# Request Models
class CheckUpdateRequest(BaseModel):
    """Request to check for firmware updates"""
    device_id: str
    current_version: str
    device_name: Optional[str] = ""
    manufacturer: Optional[str] = ""
    model: Optional[str] = ""


class InstallUpdateRequest(BaseModel):
    """Request to install firmware update"""
    device_id: str
    backup_current: bool = True
    auto_rollback_timeout: Optional[int] = 300  # seconds


class RollbackRequest(BaseModel):
    """Request to rollback firmware"""
    device_id: str


# Device Endpoints
@router.get("/devices")
async def list_iot_devices(sys: SystemContainer = Depends(get_system_state)):
    """
    List Matter/ESP32 devices.
    
    Returns all discovered Matter devices with their status and firmware info.
    """
    devices = []
    
    if sys.matter_controller:
        try:
            # Try get_nodes first
            if hasattr(sys.matter_controller, 'get_nodes'):
                nodes = sys.matter_controller.get_nodes()
                if nodes:
                    logger.info(f"Returning {len(nodes)} Matter devices")
                    return nodes
            
            # Fallback: use discovery
            discovered = sys.matter_controller.discover()
            
            # Handle different return types
            if isinstance(discovered, dict):
                for device_id, info in discovered.items():
                    devices.append({
                        "id": device_id,
                        "name": info.get("name", device_id) if isinstance(info, dict) else device_id,
                        "type": info.get("type", "unknown") if isinstance(info, dict) else "unknown",
                        "node_id": info.get("node_id") if isinstance(info, dict) else None,
                        "endpoint": info.get("endpoint") if isinstance(info, dict) else None,
                        "room": info.get("room") if isinstance(info, dict) else None,
                        "firmware_version": info.get("firmware_version", "unknown") if isinstance(info, dict) else "unknown",
                        "status": "online" if (isinstance(info, dict) and info.get("endpoints")) else "offline"
                    })
            elif isinstance(discovered, list):
                devices = discovered
            
            logger.info(f"Returning {len(devices)} discovered devices")
            
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
    
    return devices


@router.get("/devices/{device_id}")
async def get_device_firmware(device_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Get firmware information for a specific device."""
    if not sys.matter_controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matter controller not initialized"
        )
    
    try:
        # Try to get device config
        if hasattr(sys.matter_controller, 'get_device_config'):
            device = sys.matter_controller.get_device_config(device_id)
            if device:
                return {
                    "device_id": device_id,
                    "device_name": device.get("name", "Unknown Device"),
                    "firmware_version": device.get("firmware_version", "Unknown"),
                    "manufacturer": device.get("manufacturer", "Unknown"),
                    "model": device.get("model", "Unknown"),
                    "update_available": False,
                }
        
        # Fallback: search in discovered devices
        discovered = sys.matter_controller.discover()
        if isinstance(discovered, dict):
            for dev_id, info in discovered.items():
                if str(dev_id) == device_id or str(info.get("node_id", "")) == device_id:
                    return {
                        "device_id": device_id,
                        "device_name": info.get("name", "Unknown Device"),
                        "firmware_version": info.get("firmware_version", "Unknown"),
                        "manufacturer": info.get("manufacturer", "Unknown"),
                        "model": info.get("model", "Unknown"),
                        "update_available": False,
                    }
        elif isinstance(discovered, list):
            for device in discovered:
                if str(device.get("id", device.get("node_id", ""))) == device_id:
                    return {
                        "device_id": device_id,
                        "device_name": device.get("name", "Unknown Device"),
                        "firmware_version": device.get("firmware_version", "Unknown"),
                        "manufacturer": device.get("manufacturer", "Unknown"),
                        "model": device.get("model", "Unknown"),
                        "update_available": False,
                    }
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} not found"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device firmware: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting device: {str(e)}"
        )


# Update Endpoints
@router.post("/check")
async def check_for_updates(
    req: CheckUpdateRequest,
    sys: SystemContainer = Depends(get_system_state)
):
    """
    Check for firmware updates for a device.
    
    Queries the manufacturer's firmware server for available updates.
    """
    ota = get_ota_manager()
    
    update = await ota.check_for_updates(
        device_id=req.device_id,
        current_version=req.current_version,
        device_name=req.device_name or "",
        manufacturer=req.manufacturer or "",
        model=req.model or "",
    )
    
    if update:
        return {
            "update_available": True,
            "device_id": req.device_id,
            "current_version": str(update.current_version),
            "available_version": str(update.available_version),
            "release_notes": update.release_notes,
            "file_size": update.file_size,
            "critical": update.critical,
            "release_date": update.release_date.isoformat() if update.release_date else None,
        }
    else:
        return {
            "update_available": False,
            "device_id": req.device_id,
            "current_version": req.current_version,
            "message": "No updates available",
        }


@router.post("/check-all")
async def check_all_devices(
    background_tasks: BackgroundTasks,
    sys: SystemContainer = Depends(get_system_state)
):
    """
    Check for firmware updates for all connected devices.
    
    Runs checks in the background and returns immediately.
    """
    if not sys.matter_controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matter controller not initialized"
        )
    
    ota = get_ota_manager()
    
    # Get all devices
    devices = []
    try:
        if hasattr(sys.matter_controller, 'get_nodes'):
            devices = sys.matter_controller.get_nodes() or []
        if not devices:
            discovered = sys.matter_controller.discover()
            if isinstance(discovered, dict):
                devices = [{"id": k, **v} for k, v in discovered.items()]
            elif isinstance(discovered, list):
                devices = discovered
    except Exception as e:
        logger.error(f"Error getting devices for update check: {e}")
    
    async def check_all():
        for device in devices:
            device_id = str(device.get("id", device.get("node_id", "")))
            current_version = device.get("firmware_version", "0.0.0")
            
            await ota.check_for_updates(
                device_id=device_id,
                current_version=current_version,
                device_name=device.get("name", ""),
                manufacturer=device.get("manufacturer", ""),
                model=device.get("model", ""),
            )
    
    background_tasks.add_task(check_all)
    
    return {
        "status": "checking",
        "device_count": len(devices),
        "message": f"Checking for updates on {len(devices)} devices"
    }


@router.post("/download/{device_id}")
async def download_update(
    device_id: str,
    sys: SystemContainer = Depends(get_system_state)
):
    """
    Download firmware update for a device.
    
    Downloads and verifies the firmware file.
    """
    ota = get_ota_manager()
    
    success = await ota.download_update(device_id)
    
    if success:
        status_info = ota.get_update_status(device_id)
        return {
            "status": "downloaded",
            "device_id": device_id,
            "message": "Firmware downloaded and verified",
            "ready_to_install": True,
        }
    else:
        status_info = ota.get_update_status(device_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=status_info.get("error", "Download failed") if status_info else "Download failed"
        )


@router.post("/install")
async def install_update(
    req: InstallUpdateRequest,
    background_tasks: BackgroundTasks,
    sys: SystemContainer = Depends(get_system_state)
):
    """
    Install firmware update on a device.
    
    This is an asynchronous operation. Use the /status endpoint to track progress.
    """
    ota = get_ota_manager()
    
    # Check if update is downloaded
    status_info = ota.get_update_status(req.device_id)
    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No update found for device {req.device_id}. Run /check first."
        )
    
    # Start installation in background
    async def install():
        await ota.install_update(
            device_id=req.device_id,
            matter_controller=sys.matter_controller,
            backup_current=req.backup_current,
        )
    
    background_tasks.add_task(install)
    
    return {
        "status": "installing",
        "device_id": req.device_id,
        "message": "Installation started. Use /status to track progress.",
    }


@router.post("/rollback")
async def rollback_firmware(
    req: RollbackRequest,
    sys: SystemContainer = Depends(get_system_state)
):
    """
    Rollback firmware to previous version.
    
    Only available if backup was made during installation.
    """
    ota = get_ota_manager()
    
    status_info = ota.get_update_status(req.device_id)
    if not status_info or not status_info.get("rollback_available"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rollback available for this device"
        )
    
    success = await ota.rollback_update(
        device_id=req.device_id,
        matter_controller=sys.matter_controller,
    )
    
    if success:
        return {
            "status": "rolled_back",
            "device_id": req.device_id,
            "message": f"Rolled back to version {status_info.get('previous_version')}",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rollback failed"
        )


# Status Endpoints
@router.get("/status/{device_id}")
async def get_update_status(device_id: str):
    """Get current firmware update status for a device."""
    ota = get_ota_manager()
    
    status_info = ota.get_update_status(device_id)
    
    if not status_info:
        return {
            "device_id": device_id,
            "status": "idle",
            "message": "No update in progress",
        }
    
    return status_info


@router.get("/status")
async def get_all_update_status():
    """Get firmware update status for all devices."""
    ota = get_ota_manager()
    
    updates = ota.get_all_updates()
    
    return {
        "updates": updates,
        "count": len(updates),
    }


@router.delete("/cancel/{device_id}")
async def cancel_update(device_id: str):
    """Cancel an in-progress firmware update."""
    ota = get_ota_manager()
    
    success = ota.cancel_update(device_id)
    
    if success:
        return {
            "status": "cancelled",
            "device_id": device_id,
            "message": "Update cancelled",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active update to cancel"
        )


@router.delete("/clear/{device_id}")
async def clear_update_data(device_id: str):
    """Clear update data for a device."""
    ota = get_ota_manager()
    
    ota.clear_update(device_id)
    
    return {
        "status": "cleared",
        "device_id": device_id,
    }


# Legacy Endpoints (for backward compatibility)
@router.post("/ota/update")
async def trigger_ota(device_id: str, version: str, sys: SystemContainer = Depends(get_system_state)):
    """
    Push firmware update to a device (legacy endpoint).
    
    Note: This is a convenience endpoint that combines check, download, and install.
    """
    logger.info(f"OTA update requested: device={device_id}, version={version}")
    
    ota = get_ota_manager()
    
    # Check for update
    update = await ota.check_for_updates(
        device_id=device_id,
        current_version="0.0.0",  # Will be updated by check
    )
    
    if not update:
        return {
            "status": "error",
            "message": f"No update available for device {device_id}",
        }
    
    # Download
    if not await ota.download_update(device_id):
        return {
            "status": "error",
            "message": "Failed to download update",
        }
    
    # Install
    success = await ota.install_update(
        device_id=device_id,
        matter_controller=sys.matter_controller,
    )
    
    if success:
        return {
            "status": "update_initiated",
            "device_id": device_id,
            "target_version": str(update.available_version),
            "eta_seconds": 120,
        }
    else:
        return {
            "status": "error",
            "message": "Installation failed",
        }


# Device Logs
@router.get("/logs")
async def get_device_logs(device_id: str = None, lines: int = 50, sys: SystemContainer = Depends(get_system_state)):
    """
    Get device logs.
    
    Note: This is a placeholder for device log retrieval.
    Real implementation would integrate with device logging systems.
    """
    if not device_id:
        # Return logs from all devices (summary)
        devices = []
        if sys.matter_controller:
            try:
                discovered = sys.matter_controller.discover()
                if isinstance(discovered, dict):
                    devices = list(discovered.keys())
                elif isinstance(discovered, list):
                    devices = [d.get("id", d.get("node_id", "")) for d in discovered]
            except (AttributeError, ConnectionError, RuntimeError) as e:
                logger.debug(f"Device discovery fallback: {e}")
        
        return {
            "note": "Specify device_id to get specific device logs",
            "available_devices": devices
        }
    
    logger.info(f"Logs requested for device: {device_id}")
    
    # Placeholder logs
    return {
        "device_id": device_id,
        "logs": [
            f"[{device_id}] Boot sequence initiated",
            f"[{device_id}] Matter fabric connection established",
            f"[{device_id}] All endpoints operational",
            f"[{device_id}] Running firmware version: unknown"
        ],
        "note": "Log retrieval is a placeholder - implement device diagnostics for production"
    }


# Device Health
@router.get("/health/{device_id}")
async def get_device_health(device_id: str, sys: SystemContainer = Depends(get_system_state)):
    """Get health status of a specific device."""
    if sys.matter_controller:
        try:
            state = sys.matter_controller.get_state(device_id)
            return {
                "device_id": device_id,
                "state": state,
                "healthy": state is not None
            }
        except Exception as e:
            logger.error(f"Error getting device health: {e}")
            return {
                "device_id": device_id,
                "state": None,
                "healthy": False,
                "error": str(e)
            }
    
    return {"device_id": device_id, "state": None, "healthy": False, "error": "No controller available"}


# Update History
@router.get("/history/{device_id}")
async def get_update_history(device_id: str):
    """Get firmware update history for a device."""
    # In production, this would query a database
    return {
        "device_id": device_id,
        "history": [
            {
                "version": "1.0.0",
                "installed_at": "2024-01-15T10:00:00Z",
                "status": "success",
            },
        ],
    }
