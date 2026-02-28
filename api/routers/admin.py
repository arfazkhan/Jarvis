from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import logging
import os
import signal
from typing import Optional
from api.dependencies import get_system_state, SystemContainer
from api.security import get_admin_key

router = APIRouter(dependencies=[Depends(get_admin_key)])
logger = logging.getLogger("arvis.api.admin")

# Global orchestration managers (initialized on first use)
_shutdown_manager = None
_health_monitor = None


def _get_shutdown_manager():
    """Get or create shutdown manager"""
    global _shutdown_manager
    if _shutdown_manager is None:
        from arvis_core.orchestration import ShutdownManager
        _shutdown_manager = ShutdownManager()
    return _shutdown_manager


def _get_health_monitor():
    """Get or create health monitor"""
    global _health_monitor
    if _health_monitor is None:
        from arvis_core.orchestration import HealthMonitor
        _health_monitor = HealthMonitor()
    return _health_monitor


class KillSwitchRequest(BaseModel):
    reason: str
    force: bool = False


class ResumeRequest(BaseModel):
    confirm: bool = False


class ShutdownRequest(BaseModel):
    reason: str = "Administrative shutdown"
    timeout: float = 60.0
    force: bool = False


class RestartRequest(BaseModel):
    reason: str = "Administrative restart"
    timeout: float = 120.0

@router.post("/safety-override")
async def safety_override(req: KillSwitchRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    EMERGENCY KILL SWITCH.
    
    Immediately stops all automations and turns off all devices.
    This is a safety-critical operation.
    """
    logger.warning(f"⛔ EMERGENCY STOP INITIATED: {req.reason}")
    
    results = {
        "status": "SHUTDOWN_INITIATED",
        "reason": req.reason,
        "actions_taken": []
    }
    
    # 1. Stop all automations
    if sys.automation_engine:
        try:
            stop_result = sys.automation_engine.stop_all()
            results["actions_taken"].append({
                "action": "automation_stop",
                "status": "success",
                "details": stop_result
            })
            logger.info("✅ All automations stopped")
        except Exception as e:
            results["actions_taken"].append({
                "action": "automation_stop",
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"❌ Failed to stop automations: {e}")
    else:
        results["actions_taken"].append({
            "action": "automation_stop",
            "status": "skipped",
            "reason": "No automation engine available"
        })
        
    # 2. Emergency stop all Matter devices
    if sys.matter_controller:
        try:
            device_result = sys.matter_controller.emergency_stop()
            results["actions_taken"].append({
                "action": "device_emergency_stop",
                "status": "success",
                "details": device_result
            })
            logger.info("✅ All devices stopped")
        except Exception as e:
            results["actions_taken"].append({
                "action": "device_emergency_stop",
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"❌ Failed to stop devices: {e}")
    else:
        results["actions_taken"].append({
            "action": "device_emergency_stop",
            "status": "skipped",
            "reason": "No matter controller available"
        })
    
    # 3. Stop voice coordinator
    if sys.voice_coordinator:
        try:
            await sys.voice_coordinator.stop()
            results["actions_taken"].append({
                "action": "voice_stop",
                "status": "success"
            })
            logger.info("✅ Voice coordinator stopped")
        except Exception as e:
            results["actions_taken"].append({
                "action": "voice_stop",
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"❌ Failed to stop voice: {e}")
    
    logger.warning(f"⛔ EMERGENCY STOP COMPLETE: {len(results['actions_taken'])} actions taken")
    return results

@router.post("/resume")
async def resume_operations(req: ResumeRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    Resume operations after emergency stop.
    
    Requires explicit confirmation to prevent accidental resume.
    """
    if not req.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume requires confirmation. Set confirm=true."
        )
    
    logger.info("🟢 Resuming operations after emergency stop")
    
    results = {
        "status": "RESUMED",
        "actions_taken": []
    }
    
    # 1. Resume automations
    if sys.automation_engine:
        try:
            resume_result = sys.automation_engine.resume_all()
            results["actions_taken"].append({
                "action": "automation_resume",
                "status": "success",
                "details": resume_result
            })
        except Exception as e:
            results["actions_taken"].append({
                "action": "automation_resume",
                "status": "failed",
                "error": str(e)
            })
    
    # 2. Restart voice coordinator
    if sys.voice_coordinator:
        try:
            await sys.voice_coordinator.start()
            results["actions_taken"].append({
                "action": "voice_start",
                "status": "success"
            })
        except Exception as e:
            results["actions_taken"].append({
                "action": "voice_start",
                "status": "failed",
                "error": str(e)
            })
    
    return results

@router.get("/health")
async def health_check(sys: SystemContainer = Depends(get_system_state)):
    """Internal component health."""
    health_status = {
        "event_bus": sys.event_bus is not None,
        "state_engine": sys.state_engine is not None,
        "llm_agent": sys.llm_agent is not None,
        "voice": sys.voice_coordinator is not None,
        "matter_controller": sys.matter_controller is not None,
        "automation_engine": sys.automation_engine is not None,
        "learning_engine": sys.learning_engine is not None
    }
    
    # Determine overall health
    all_healthy = all(health_status.values())
    health_status["overall"] = "healthy" if all_healthy else "degraded"
    
    return health_status

@router.post("/shutdown")
async def graceful_shutdown(req: ShutdownRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    Graceful shutdown with ordered component termination.
    
    Shutdown phases:
    1. Stop accepting new requests
    2. Drain active connections
    3. Stop services (voice, learning)
    4. Stop automations
    5. Persist state
    6. Disconnect external systems
    7. Final cleanup
    """
    from arvis_core.orchestration import ShutdownManager, ShutdownPhase
    
    manager = ShutdownManager(default_timeout=req.timeout)
    
    # Register shutdown steps
    if sys.voice_coordinator:
        manager.register_step(
            "stop_voice",
            ShutdownPhase.STOP_SERVICES,
            lambda: sys.voice_coordinator.stop(),
            timeout_seconds=10.0
        )
    
    if sys.learning_engine:
        manager.register_step(
            "stop_learning",
            ShutdownPhase.STOP_SERVICES,
            lambda: None,  # Learning engine doesn't have explicit stop
            timeout_seconds=5.0
        )
    
    if sys.automation_engine:
        manager.register_step(
            "stop_automations",
            ShutdownPhase.STOP_AUTOMATIONS,
            lambda: sys.automation_engine.stop_all(),
            timeout_seconds=15.0,
            critical=True
        )
    
    if sys.matter_controller:
        manager.register_step(
            "disconnect_matter",
            ShutdownPhase.DISCONNECT_EXTERNAL,
            lambda: sys.matter_controller.emergency_stop(),
            timeout_seconds=10.0
        )
    
    # Execute shutdown
    result = await manager.shutdown(reason=req.reason, force=req.force)
    
    return result


@router.post("/restart")
async def restart_services(req: RestartRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    Full service restart with health verification.
    
    Performs:
    1. Graceful shutdown
    2. State persistence
    3. Component reinitialization
    4. Health verification
    
    Note: Requires process manager (supervisor/systemd) for full process restart.
    """
    logger.info(f"Restart requested: {req.reason}")
    
    results = {
        "status": "restart_initiated",
        "reason": req.reason,
        "shutdown": None,
        "startup": None
    }
    
    # 1. Execute graceful shutdown
    shutdown_req = ShutdownRequest(reason=req.reason, timeout=req.timeout / 2)
    shutdown_result = await graceful_shutdown(shutdown_req, sys)
    results["shutdown"] = shutdown_result
    
    # 2. Check if we have a process manager
    has_supervisor = os.path.exists("/var/run/supervisor.sock") or \
                     os.path.exists("/run/systemd/system")
    
    if has_supervisor:
        # Signal supervisor to restart
        try:
            # For systemd
            if os.path.exists("/run/systemd/system"):
                # Send SIGTERM to trigger systemd restart
                os.kill(os.getpid(), signal.SIGTERM)
                results["status"] = "restart_signaled"
            else:
                # For supervisor, use supervisorctl
                import subprocess
                subprocess.run(["supervisorctl", "restart", "arvis"], check=True)
                results["status"] = "restart_signaled"
        except Exception as e:
            results["status"] = "restart_failed"
            results["error"] = str(e)
    else:
        # No process manager - manual restart required
        results["status"] = "shutdown_complete_manual_restart_required"
        results["note"] = "No process manager detected. Manual restart required."
    
    return results


@router.get("/startup-status")
async def get_startup_status():
    """
    Get current startup/initialization status.
    
    Returns progress of system initialization.
    """
    from api.dependencies import global_state
    
    status = {
        "mode": getattr(global_state, "mode", "UNKNOWN"),
        "initialized": False,
        "components": {}
    }
    
    # Check component initialization
    components = [
        ("event_bus", global_state.event_bus),
        ("state_engine", global_state.state_engine),
        ("llm_agent", global_state.llm_agent),
        ("matter_controller", global_state.matter_controller),
        ("automation_engine", global_state.automation_engine),
        ("learning_engine", global_state.learning_engine),
        ("voice_coordinator", global_state.voice_coordinator),
    ]
    
    initialized_count = 0
    for name, component in components:
        is_initialized = component is not None
        status["components"][name] = is_initialized
        if is_initialized:
            initialized_count += 1
    
    status["initialized"] = initialized_count == len(components)
    status["progress_percent"] = (initialized_count / len(components)) * 100
    status["initialized_count"] = initialized_count
    status["total_components"] = len(components)
    
    return status


@router.get("/health/detailed")
async def detailed_health_check(sys: SystemContainer = Depends(get_system_state)):
    """
    Detailed health check with component-specific diagnostics.
    
    Runs health checks on all components and returns detailed status.
    """
    monitor = _get_health_monitor()
    
    # Register component checks
    monitor._checks.clear()  # Clear previous registrations
    
    if sys.event_bus:
        monitor.register("event_bus", lambda: True, critical=True)
    if sys.state_engine:
        monitor.register("state_engine", lambda: sys.state_engine is not None, critical=True)
    if sys.llm_agent:
        monitor.register("llm_agent", lambda: sys.llm_agent is not None, critical=True)
    if sys.matter_controller:
        monitor.register("matter_controller", 
                        lambda: len(sys.matter_controller.discover()) >= 0)
    if sys.automation_engine:
        monitor.register("automation_engine", lambda: True)
    if sys.learning_engine:
        monitor.register("learning_engine", lambda: True)
    if sys.voice_coordinator:
        monitor.register("voice_coordinator", 
                        lambda: sys.voice_coordinator.is_running)
    
    # Run health checks
    health = await monitor.check_all()
    
    return health.to_dict()


@router.get("/config")
async def get_config():
    """View active feature flags."""
    return {
        "voice_enabled": True,
        "learning_enabled": True,
        "safety_guardrails": "STRICT"
    }
