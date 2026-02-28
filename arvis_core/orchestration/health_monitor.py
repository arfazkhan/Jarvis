"""
Health Monitor
==============

Monitors health of ARVIS components and provides health check endpoints.

Features:
- Component health checks
- Aggregated health status
- Health history tracking
- Alerting on degraded state
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("arvis.orchestration.health")


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component"""
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    last_check: Optional[datetime] = None
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "latency_ms": self.latency_ms,
            "details": self.details
        }


@dataclass
class SystemHealth:
    """Overall system health"""
    status: HealthStatus = HealthStatus.UNKNOWN
    components: List[ComponentHealth] = field(default_factory=list)
    checked_at: Optional[datetime] = None
    uptime_seconds: float = 0.0
    startup_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "components": [c.to_dict() for c in self.components],
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "uptime_seconds": self.uptime_seconds,
            "startup_time": self.startup_time.isoformat() if self.startup_time else None,
            "healthy_count": sum(1 for c in self.components if c.status == HealthStatus.HEALTHY),
            "degraded_count": sum(1 for c in self.components if c.status == HealthStatus.DEGRADED),
            "unhealthy_count": sum(1 for c in self.components if c.status == HealthStatus.UNHEALTHY)
        }


class HealthMonitor:
    """
    Monitors health of ARVIS components.
    
    Usage:
        monitor = HealthMonitor()
        monitor.register("event_bus", lambda: event_bus is not None)
        monitor.register("database", check_database_connection)
        
        # Get health status
        health = await monitor.check_all()
    """
    
    def __init__(self, startup_time: Optional[datetime] = None):
        """
        Initialize health monitor.
        
        Args:
            startup_time: When the system started
        """
        self.startup_time = startup_time or datetime.now()
        self._checks: Dict[str, Callable] = {}
        self._component_info: Dict[str, Dict[str, Any]] = {}
        self._last_health: Optional[SystemHealth] = None
        
    def register(
        self,
        name: str,
        check_func: Callable,
        description: str = "",
        critical: bool = False
    ) -> None:
        """
        Register a health check.
        
        Args:
            name: Component name
            check_func: Function that returns True if healthy, or raises exception
            description: Human-readable description
            critical: If True, component failure makes system unhealthy
        """
        self._checks[name] = check_func
        self._component_info[name] = {
            "description": description,
            "critical": critical
        }
        logger.debug(f"Registered health check: {name} (critical={critical})")
    
    async def check(self, name: str) -> ComponentHealth:
        """
        Check health of a single component.
        
        Args:
            name: Component name
            
        Returns:
            ComponentHealth with status
        """
        if name not in self._checks:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNKNOWN,
                message="Component not registered"
            )
        
        check_func = self._checks[name]
        start_time = time.time()
        
        try:
            # Execute check
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Determine status
            if result is True:
                status = HealthStatus.HEALTHY
                message = "OK"
            elif result is False:
                status = HealthStatus.UNHEALTHY
                message = "Check returned False"
            elif isinstance(result, dict):
                # Detailed result
                status = HealthStatus(result.get("status", "healthy"))
                message = result.get("message", "")
                details = result.get("details", {})
            else:
                status = HealthStatus.HEALTHY
                message = str(result) if result else "OK"
            
            return ComponentHealth(
                name=name,
                status=status,
                message=message,
                last_check=datetime.now(),
                latency_ms=latency_ms,
                details=locals().get("details", {})
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(),
                latency_ms=latency_ms
            )
    
    async def check_all(self) -> SystemHealth:
        """
        Check health of all registered components.
        
        Returns:
            SystemHealth with aggregated status
        """
        components = []
        has_unhealthy = False
        has_degraded = False
        has_critical_failure = False
        
        # Run all checks in parallel
        tasks = [self.check(name) for name in self._checks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for name, result in zip(self._checks.keys(), results):
            if isinstance(result, Exception):
                health = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(result)
                )
            else:
                health = result
            
            components.append(health)
            
            # Track status
            if health.status == HealthStatus.UNHEALTHY:
                has_unhealthy = True
                if self._component_info.get(name, {}).get("critical", False):
                    has_critical_failure = True
            elif health.status == HealthStatus.DEGRADED:
                has_degraded = True
        
        # Determine overall status
        if has_critical_failure or has_unhealthy:
            status = HealthStatus.UNHEALTHY
        elif has_degraded:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY
        
        # Calculate uptime
        uptime = (datetime.now() - self.startup_time).total_seconds()
        
        self._last_health = SystemHealth(
            status=status,
            components=components,
            checked_at=datetime.now(),
            uptime_seconds=uptime,
            startup_time=self.startup_time
        )
        
        return self._last_health
    
    def get_last_health(self) -> Optional[SystemHealth]:
        """Get last health check result without running new checks"""
        return self._last_health
    
    def get_summary(self) -> Dict[str, Any]:
        """Get health summary"""
        if not self._last_health:
            return {
                "status": "not_checked",
                "registered_components": list(self._checks.keys())
            }
        
        return self._last_health.to_dict()
    
    def get_component(self, name: str) -> Optional[ComponentHealth]:
        """Get health of a specific component from last check"""
        if not self._last_health:
            return None
        
        for component in self._last_health.components:
            if component.name == name:
                return component
        
        return None
    
    @property
    def is_healthy(self) -> bool:
        """Quick check if system is healthy"""
        if not self._last_health:
            return False
        return self._last_health.status == HealthStatus.HEALTHY
    
    @property
    def is_degraded(self) -> bool:
        """Check if system is degraded"""
        if not self._last_health:
            return False
        return self._last_health.status == HealthStatus.DEGRADED