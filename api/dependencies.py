"""
ARVIS API Dependencies
======================

FastAPI dependency injection for ARVIS components.
Uses the central DI container for service resolution.
"""

from typing import Generator, Optional
from fastapi import Request

# Import from the central DI container
from arvis_core.container import (
    Container,
    get_container,
    get_event_bus as _get_event_bus,
    get_llm_agent as _get_llm_agent,
    SystemContainer,
    global_state,
)


def get_system_state() -> SystemContainer:
    """Dependency to get the initialized system state."""
    return global_state


def get_event_bus():
    """Get the event bus from the container."""
    return _get_event_bus()


def get_llm_agent():
    """Get the LLM agent from the container."""
    return _get_llm_agent()


def get_container_dep() -> Container:
    """FastAPI dependency to get the DI container."""
    return get_container()


# Legacy exports for backward compatibility
__all__ = [
    "get_system_state",
    "get_event_bus", 
    "get_llm_agent",
    "get_container_dep",
    "SystemContainer",
    "global_state",
]
