"""
ARVIS Core
==========

Core infrastructure for the ARVIS system including:
- Dependency Injection Container
- Orchestration (Startup/Shutdown/Health)
- Memory System
- Event Bus
"""

from arvis_core.container import (
    Container,
    get_container,
    reset_container,
    get_event_bus,
    get_state_engine,
    get_llm_agent,
    get_matter_controller,
    get_automation_engine,
    get_learning_engine,
    get_bms_agent,
    get_real_bms,
    get_database,
    get_safety_controller,
    get_mode_dispatcher,
    SystemContainer,
    global_state,
)

from arvis_core.orchestration import (
    ShutdownManager,
    StartupManager,
    HealthMonitor,
    ComponentHealth,
    get_shutdown_manager,
    get_startup_manager,
    get_health_monitor,
)

__all__ = [
    # Container
    "Container",
    "get_container",
    "reset_container",
    "get_event_bus",
    "get_state_engine",
    "get_llm_agent",
    "get_matter_controller",
    "get_automation_engine",
    "get_learning_engine",
    "get_bms_agent",
    "get_real_bms",
    "get_database",
    "get_safety_controller",
    "get_mode_dispatcher",
    "SystemContainer",
    "global_state",
    # Orchestration
    "ShutdownManager",
    "StartupManager",
    "HealthMonitor",
    "ComponentHealth",
    "get_shutdown_manager",
    "get_startup_manager",
    "get_health_monitor",
]
