"""
ARVIS Dependency Injection Container
=====================================

Replaces singleton globals with proper dependency injection.
This enables better testability and decoupled components.

Usage:
    # Initialize container at application startup
    container = Container()
    container.register("event_bus", EventBus())
    container.register("state_engine", StateEngine())
    
    # Resolve dependencies
    event_bus = container.resolve("event_bus")
    
    # Or use dependency injection in FastAPI
    @router.get("/status")
    def get_status(container: Container = Depends(get_container)):
        state = container.resolve("state_engine")
        return state.get_status()
"""

from typing import Any, Callable, Dict, Optional, Type, TypeVar
from dataclasses import dataclass, field
import logging
import threading

logger = logging.getLogger("arvis.container")

T = TypeVar("T")


@dataclass
class ServiceDescriptor:
    """Describes a registered service."""
    factory: Optional[Callable] = None
    instance: Optional[Any] = None
    singleton: bool = True
    initialized: bool = False


class Container:
    """
    Dependency Injection Container for ARVIS.
    
    Thread-safe implementation supporting:
    - Singleton and transient lifecycles
    - Factory-based registration
    - Instance-based registration
    - Lazy initialization
    """
    
    _instance: Optional["Container"] = None
    _lock = threading.Lock()
    
    def __init__(self):
        self._services: Dict[str, ServiceDescriptor] = {}
        self._resolving: set = set()  # Circular dependency detection
        self._lock = threading.RLock()
    
    @classmethod
    def get_instance(cls) -> "Container":
        """Get the global container instance (for backward compatibility)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the global container (for testing)."""
        with cls._lock:
            cls._instance = None
    
    def register(
        self,
        name: str,
        service: Any = None,
        factory: Callable = None,
        singleton: bool = True
    ) -> None:
        """
        Register a service with the container.
        
        Args:
            name: Service name for resolution
            service: Service instance (for instance registration)
            factory: Callable that creates the service (for lazy registration)
            singleton: If True, only one instance is created and reused
        """
        with self._lock:
            if service is not None:
                self._services[name] = ServiceDescriptor(
                    instance=service,
                    singleton=True,
                    initialized=True
                )
                logger.debug(f"[Container] Registered instance: {name}")
            elif factory is not None:
                self._services[name] = ServiceDescriptor(
                    factory=factory,
                    singleton=singleton
                )
                logger.debug(f"[Container] Registered factory: {name} (singleton={singleton})")
            else:
                raise ValueError(f"Must provide either service or factory for {name}")
    
    def resolve(self, name: str) -> Any:
        """
        Resolve a service from the container.
        
        Args:
            name: Service name to resolve
            
        Returns:
            The service instance
            
        Raises:
            KeyError: If service is not registered
            RuntimeError: If circular dependency detected
        """
        with self._lock:
            if name not in self._services:
                raise KeyError(f"Service '{name}' is not registered")
            
            descriptor = self._services[name]
            
            # Return existing instance if already initialized (singleton)
            if descriptor.initialized and descriptor.singleton:
                return descriptor.instance
            
            # Detect circular dependencies
            if name in self._resolving:
                raise RuntimeError(f"Circular dependency detected for '{name}'")
            
            self._resolving.add(name)
            try:
                # Create instance using factory
                if descriptor.factory:
                    instance = descriptor.factory()
                else:
                    instance = descriptor.instance
                
                # Store if singleton
                if descriptor.singleton:
                    descriptor.instance = instance
                    descriptor.initialized = True
                
                return instance
            finally:
                self._resolving.discard(name)
    
    def try_resolve(self, name: str) -> Optional[Any]:
        """
        Try to resolve a service, returning None if not found.
        
        Args:
            name: Service name to resolve
            
        Returns:
            The service instance or None
        """
        try:
            return self.resolve(name)
        except KeyError:
            return None
    
    def is_registered(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._services
    
    def unregister(self, name: str) -> bool:
        """Remove a service from the container."""
        with self._lock:
            if name in self._services:
                del self._services[name]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all registered services."""
        with self._lock:
            self._services.clear()
    
    def get_all_services(self) -> Dict[str, Any]:
        """Get all registered service names and their instances."""
        return {name: self.resolve(name) for name in self._services.keys()}


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL CONTAINER INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

def get_container() -> Container:
    """Get the global container instance."""
    return Container.get_instance()


def reset_container():
    """Reset the global container (for testing)."""
    Container.reset()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS FOR COMMON SERVICES
# ═══════════════════════════════════════════════════════════════════════════════

def get_event_bus():
    """Get the event bus from the container."""
    return get_container().try_resolve("event_bus")


def get_state_engine():
    """Get the state engine from the container."""
    return get_container().try_resolve("state_engine")


def get_llm_agent():
    """Get the LLM agent from the container."""
    return get_container().try_resolve("llm_agent")


def get_matter_controller():
    """Get the Matter controller from the container."""
    return get_container().try_resolve("matter_controller")


def get_automation_engine():
    """Get the automation engine from the container."""
    return get_container().try_resolve("automation_engine")


def get_learning_engine():
    """Get the learning engine from the container."""
    return get_container().try_resolve("learning_engine")


def get_bms_agent():
    """Get the BMS agent from the container."""
    return get_container().try_resolve("bms_agent")


def get_real_bms():
    """Get the RealBMS instance from the container."""
    return get_container().try_resolve("real_bms")


def get_database():
    """Get the database instance from the container."""
    return get_container().try_resolve("database")


def get_safety_controller():
    """Get the safety controller from the container."""
    return get_container().try_resolve("safety_controller")


def get_mode_dispatcher():
    """Get the mode dispatcher from the container."""
    return get_container().try_resolve("mode_dispatcher")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY: SystemContainer
# ═══════════════════════════════════════════════════════════════════════════════

class SystemContainer:
    """
    Backward compatibility wrapper around the DI container.
    
    This class provides attribute-style access to services for legacy code.
    New code should use the container directly.
    """
    
    def __init__(self):
        self._container = get_container()
    
    def __getattr__(self, name: str) -> Any:
        """Resolve service on attribute access."""
        return self._container.try_resolve(name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Register service on attribute set."""
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._container.register(name, service=value)


# Global instance for backward compatibility
global_state = SystemContainer()


__all__ = [
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
]
