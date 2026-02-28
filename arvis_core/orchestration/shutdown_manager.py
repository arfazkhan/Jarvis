"""
Shutdown Manager
================

Manages graceful shutdown of ARVIS components in a controlled sequence.

Shutdown Phases:
1. STOP_NEW_REQUESTS - Stop accepting new API requests
2. DRAIN_CONNECTIONS - Wait for active requests to complete
3. STOP_SERVICES - Stop background services (voice, learning, etc.)
4. STOP_AUTOMATIONS - Stop all running automations
5. PERSIST_STATE - Save state to disk
6. DISCONNECT_EXTERNAL - Disconnect from external systems (BACnet, Matter)
7. FINAL_CLEANUP - Release resources, close connections
"""

import asyncio
import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime

logger = logging.getLogger("arvis.orchestration.shutdown")


class ShutdownPhase(Enum):
    """Ordered shutdown phases"""
    IDLE = "idle"
    STOP_NEW_REQUESTS = "stop_new_requests"
    DRAIN_CONNECTIONS = "drain_connections"
    STOP_SERVICES = "stop_services"
    STOP_AUTOMATIONS = "stop_automations"
    PERSIST_STATE = "persist_state"
    DISCONNECT_EXTERNAL = "disconnect_external"
    FINAL_CLEANUP = "final_cleanup"
    COMPLETE = "complete"


@dataclass
class ShutdownStep:
    """Represents a single shutdown step"""
    name: str
    phase: ShutdownPhase
    handler: Callable
    timeout_seconds: float = 30.0
    critical: bool = False  # If True, failure stops shutdown sequence
    completed: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class ShutdownState:
    """Current shutdown state"""
    phase: ShutdownPhase = ShutdownPhase.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    steps: List[ShutdownStep] = field(default_factory=list)
    reason: str = ""
    forced: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "reason": self.reason,
            "forced": self.forced,
            "steps": [
                {
                    "name": s.name,
                    "phase": s.phase.value,
                    "completed": s.completed,
                    "error": s.error,
                    "duration_ms": s.duration_ms
                }
                for s in self.steps
            ]
        }


class ShutdownManager:
    """
    Manages graceful shutdown of ARVIS components.
    
    Usage:
        manager = ShutdownManager()
        manager.register_step("stop_voice", ShutdownPhase.STOP_SERVICES, 
                              lambda: voice_coordinator.stop())
        
        # Initiate shutdown
        result = await manager.shutdown(reason="Maintenance", timeout=60)
    """
    
    def __init__(self, default_timeout: float = 120.0):
        """
        Initialize shutdown manager.
        
        Args:
            default_timeout: Maximum time for entire shutdown sequence
        """
        self.default_timeout = default_timeout
        self.state = ShutdownState()
        self._steps: Dict[ShutdownPhase, List[ShutdownStep]] = {
            phase: [] for phase in ShutdownPhase
        }
        self._is_shutting_down = False
        self._shutdown_event = asyncio.Event()
        
    def register_step(
        self,
        name: str,
        phase: ShutdownPhase,
        handler: Callable,
        timeout_seconds: float = 30.0,
        critical: bool = False
    ) -> None:
        """
        Register a shutdown step.
        
        Args:
            name: Unique name for this step
            phase: Which phase this step belongs to
            handler: Async or sync function to execute
            timeout_seconds: Maximum time for this step
            critical: If True, failure stops shutdown
        """
        step = ShutdownStep(
            name=name,
            phase=phase,
            handler=handler,
            timeout_seconds=timeout_seconds,
            critical=critical
        )
        self._steps[phase].append(step)
        logger.debug(f"Registered shutdown step: {name} (phase={phase.value})")
    
    async def shutdown(
        self,
        reason: str = "System shutdown",
        timeout: Optional[float] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Execute graceful shutdown sequence.
        
        Args:
            reason: Reason for shutdown
            timeout: Maximum time for shutdown (uses default if None)
            force: If True, skip non-critical steps on failure
            
        Returns:
            Shutdown state summary
        """
        if self._is_shutting_down:
            logger.warning("Shutdown already in progress")
            return self.state.to_dict()
        
        self._is_shutting_down = True
        self._shutdown_event.clear()
        
        timeout = timeout or self.default_timeout
        
        # Initialize state
        self.state = ShutdownState(
            phase=ShutdownPhase.STOP_NEW_REQUESTS,
            started_at=datetime.now(),
            reason=reason,
            forced=force
        )
        
        logger.info(f" Initiating graceful shutdown: {reason}")
        
        try:
            # Execute phases in order
            phases = [
                ShutdownPhase.STOP_NEW_REQUESTS,
                ShutdownPhase.DRAIN_CONNECTIONS,
                ShutdownPhase.STOP_SERVICES,
                ShutdownPhase.STOP_AUTOMATIONS,
                ShutdownPhase.PERSIST_STATE,
                ShutdownPhase.DISCONNECT_EXTERNAL,
                ShutdownPhase.FINAL_CLEANUP,
            ]
            
            for phase in phases:
                self.state.phase = phase
                logger.info(f"Shutdown phase: {phase.value}")
                
                phase_start = time.time()
                phase_success = await self._execute_phase(phase, force)
                phase_duration = (time.time() - phase_start) * 1000
                
                if not phase_success and not force:
                    logger.error(f"Shutdown failed at phase: {phase.value}")
                    break
            
            # Mark complete
            self.state.phase = ShutdownPhase.COMPLETE
            self.state.completed_at = datetime.now()
            
            total_duration = (self.state.completed_at - self.state.started_at).total_seconds()
            logger.info(f"Shutdown complete in {total_duration:.1f}s")
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            self.state.phase = ShutdownPhase.IDLE
        finally:
            self._is_shutting_down = False
            self._shutdown_event.set()
        
        return self.state.to_dict()
    
    async def _execute_phase(self, phase: ShutdownPhase, force: bool) -> bool:
        """Execute all steps in a phase"""
        steps = self._steps.get(phase, [])
        
        if not steps:
            logger.debug(f"No steps registered for phase: {phase.value}")
            return True
        
        for step in steps:
            step_start = time.time()
            
            try:
                # Execute handler with timeout
                if asyncio.iscoroutinefunction(step.handler):
                    await asyncio.wait_for(
                        step.handler(),
                        timeout=step.timeout_seconds
                    )
                else:
                    # Run sync function in executor
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        step.handler
                    )
                
                step.completed = True
                step.duration_ms = (time.time() - step_start) * 1000
                logger.info(f"  Step completed: {step.name} ({step.duration_ms:.0f}ms)")
                
            except asyncio.TimeoutError:
                step.error = f"Timeout after {step.timeout_seconds}s"
                logger.error(f"  Step timed out: {step.name}")
                
                if step.critical and not force:
                    return False
                    
            except Exception as e:
                step.error = str(e)
                logger.error(f"  Step failed: {step.name} - {e}")
                
                if step.critical and not force:
                    return False
            
            self.state.steps.append(step)
        
        return True
    
    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress"""
        return self._is_shutting_down
    
    async def wait_for_shutdown(self, timeout: float = 30.0) -> bool:
        """Wait for shutdown to complete"""
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=timeout
            )
            return True
        except asyncio.TimeoutError:
            return False
    
    def get_state(self) -> Dict[str, Any]:
        """Get current shutdown state"""
        return self.state.to_dict()