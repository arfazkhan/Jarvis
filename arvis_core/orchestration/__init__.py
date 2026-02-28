"""
ARVIS Orchestration Module
==========================

Provides system-level orchestration for:
- Graceful shutdown sequences
- Ordered startup initialization
- Component health monitoring
- State persistence across restarts
"""

from .shutdown_manager import ShutdownManager, ShutdownPhase
from .startup_manager import StartupManager, StartupPhase
from .health_monitor import HealthMonitor, ComponentHealth, HealthStatus, SystemHealth

# Singleton instances
_shutdown_manager: ShutdownManager = None
_startup_manager: StartupManager = None
_health_monitor: HealthMonitor = None


def get_shutdown_manager() -> ShutdownManager:
    """Get or create the global shutdown manager."""
    global _shutdown_manager
    if _shutdown_manager is None:
        _shutdown_manager = ShutdownManager()
    return _shutdown_manager


def get_startup_manager() -> StartupManager:
    """Get or create the global startup manager."""
    global _startup_manager
    if _startup_manager is None:
        _startup_manager = StartupManager()
    return _startup_manager


def get_health_monitor() -> HealthMonitor:
    """Get or create the global health monitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


__all__ = [
    "ShutdownManager",
    "ShutdownPhase",
    "StartupManager", 
    "StartupPhase",
    "HealthMonitor",
    "ComponentHealth",
    "HealthStatus",
    "SystemHealth",
    "get_shutdown_manager",
    "get_startup_manager",
    "get_health_monitor",
]
