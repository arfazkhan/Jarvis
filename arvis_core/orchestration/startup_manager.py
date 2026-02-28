"""
Startup Manager
===============

Manages ordered startup of ARVIS components with health verification.

Startup Phases:
1. CORE_INIT - Initialize core infrastructure (EventBus, Memory)
2. DATA_LAYER - Initialize data stores and persistence
3. EXTERNAL_ADAPTERS - Connect to external systems (BACnet, Matter)
4. SERVICES - Start background services (Voice, Learning)
5. API_LAYER - Start API server
6. VERIFICATION - Verify all components are healthy
"""

import asyncio
import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime

logger = logging.getLogger("arvis.orchestration.startup")


class StartupPhase(Enum):
    """Ordered startup phases"""
    IDLE = "idle"
    CORE_INIT = "core_init"
    DATA_LAYER = "data_layer"
    EXTERNAL_ADAPTERS = "external_adapters"
    SERVICES = "services"
    API_LAYER = "api_layer"
    VERIFICATION = "verification"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class StartupStep:
    """Represents a single startup step"""
    name: str
    phase: StartupPhase
    handler: Callable
    health_check: Optional[Callable] = None
    timeout_seconds: float = 30.0
    retry_count: int = 3
    retry_delay_seconds: float = 1.0
    critical: bool = False
    completed: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0
    attempts: int = 0


@dataclass
class StartupState:
    """Current startup state"""
    phase: StartupPhase = StartupPhase.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    steps: List[StartupStep] = field(default_factory=list)
    mode: str = "RESIDENTIAL"  # RESIDENTIAL or COMMERCIAL
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "mode": self.mode,
            "steps": [
                {
                    "name": s.name,
                    "phase": s.phase.value,
                    "completed": s.completed,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                    "attempts": s.attempts
                }
                for s in self.steps
            ]
        }
    
    @property
    def progress_percent(self) -> float:
        """Calculate startup progress percentage"""
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.completed)
        return (completed / len(self.steps)) * 100


class StartupManager:
    """
    Manages ordered startup of ARVIS components.
    
    Usage:
        manager = StartupManager()
        manager.register_step("event_bus", StartupPhase.CORE_INIT,
                              lambda: EventBus(), critical=True)
        
        # Execute startup
        result = await manager.startup(mode="RESIDENTIAL")
    """
    
    def __init__(self, default_timeout: float = 180.0):
        """
        Initialize startup manager.
        
        Args:
            default_timeout: Maximum time for entire startup sequence
        """
        self.default_timeout = default_timeout
        self.state = StartupState()
        self._steps: Dict[StartupPhase, List[StartupStep]] = {
            phase: [] for phase in StartupPhase
        }
        self._is_starting = False
        self._startup_complete = asyncio.Event()
        
    def register_step(
        self,
        name: str,
        phase: StartupPhase,
        handler: Callable,
        health_check: Optional[Callable] = None,
        timeout_seconds: float = 30.0,
        retry_count: int = 3,
        retry_delay_seconds: float = 1.0,
        critical: bool = False
    ) -> None:
        """
        Register a startup step.
        
        Args:
            name: Unique name for this step
            phase: Which phase this step belongs to
            handler: Async or sync function to execute
            health_check: Optional function to verify step success
            timeout_seconds: Maximum time for this step
            retry_count: Number of retry attempts
            retry_delay_seconds: Delay between retries
            critical: If True, failure stops startup
        """
        step = StartupStep(
            name=name,
            phase=phase,
            handler=handler,
            health_check=health_check,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            retry_delay_seconds=retry_delay_seconds,
            critical=critical
        )
        self._steps[phase].append(step)
        logger.debug(f"Registered startup step: {name} (phase={phase.value})")
    
    async def startup(
        self,
        mode: str = "RESIDENTIAL",
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Execute startup sequence.
        
        Args:
            mode: ARVIS mode (RESIDENTIAL or COMMERCIAL)
            timeout: Maximum time for startup (uses default if None)
            
        Returns:
            Startup state summary
        """
        if self._is_starting:
            logger.warning("Startup already in progress")
            return self.state.to_dict()
        
        self._is_starting = True
        self._startup_complete.clear()
        
        timeout = timeout or self.default_timeout
        
        # Initialize state
        self.state = StartupState(
            phase=StartupPhase.CORE_INIT,
            started_at=datetime.now(),
            mode=mode
        )
        
        logger.info(f"🚀 Starting ARVIS in {mode} mode...")
        
        try:
            # Execute phases in order
            phases = [
                StartupPhase.CORE_INIT,
                StartupPhase.DATA_LAYER,
                StartupPhase.EXTERNAL_ADAPTERS,
                StartupPhase.SERVICES,
                StartupPhase.API_LAYER,
                StartupPhase.VERIFICATION,
            ]
            
            for phase in phases:
                self.state.phase = phase
                logger.info(f"Startup phase: {phase.value}")
                
                phase_start = time.time()
                phase_success = await self._execute_phase(phase)
                phase_duration = (time.time() - phase_start) * 1000
                
                if not phase_success:
                    logger.error(f"Startup failed at phase: {phase.value}")
                    self.state.phase = StartupPhase.FAILED
                    break
            
            # Mark complete if all phases succeeded
            if self.state.phase != StartupPhase.FAILED:
                self.state.phase = StartupPhase.COMPLETE
                self.state.completed_at = datetime.now()
                
                total_duration = (self.state.completed_at - self.state.started_at).total_seconds()
                logger.info(f"✅ ARVIS startup complete in {total_duration:.1f}s "
                           f"({self.state.progress_percent:.0f}% success)")
            
        except Exception as e:
            logger.error(f"Startup error: {e}")
            self.state.phase = StartupPhase.FAILED
        finally:
            self._is_starting = False
            self._startup_complete.set()
        
        return self.state.to_dict()
    
    async def _execute_phase(self, phase: StartupPhase) -> bool:
        """Execute all steps in a phase"""
        steps = self._steps.get(phase, [])
        
        if not steps:
            logger.debug(f"No steps registered for phase: {phase.value}")
            return True
        
        for step in steps:
            step_start = time.time()
            step.attempts = 0
            
            # Retry loop
            while step.attempts < step.retry_count:
                step.attempts += 1
                
                try:
                    # Execute handler with timeout
                    if asyncio.iscoroutinefunction(step.handler):
                        result = await asyncio.wait_for(
                            step.handler(),
                            timeout=step.timeout_seconds
                        )
                    else:
                        # Run sync function in executor
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, step.handler)
                    
                    # Run health check if provided
                    if step.health_check:
                        if asyncio.iscoroutinefunction(step.health_check):
                            health_ok = await step.health_check()
                        else:
                            health_ok = step.health_check()
                        
                        if not health_ok:
                            raise RuntimeError(f"Health check failed for {step.name}")
                    
                    step.completed = True
                    step.duration_ms = (time.time() - step_start) * 1000
                    logger.info(f"  ✅ Step completed: {step.name} ({step.duration_ms:.0f}ms, "
                               f"{step.attempts} attempt(s))")
                    break
                    
                except asyncio.TimeoutError:
                    step.error = f"Timeout after {step.timeout_seconds}s"
                    logger.warning(f"  ⏱️ Step timed out: {step.name} (attempt {step.attempts}/{step.retry_count})")
                    
                    if step.attempts < step.retry_count:
                        await asyncio.sleep(step.retry_delay_seconds)
                        
                except Exception as e:
                    step.error = str(e)
                    logger.warning(f"  ❌ Step failed: {step.name} - {e} (attempt {step.attempts}/{step.retry_count})")
                    
                    if step.attempts < step.retry_count:
                        await asyncio.sleep(step.retry_delay_seconds)
            
            # Check if step completed
            if not step.completed:
                logger.error(f"  ❌ Step failed after {step.retry_count} attempts: {step.name}")
                
                if step.critical:
                    return False
            
            self.state.steps.append(step)
        
        return True
    
    @property
    def is_starting(self) -> bool:
        """Check if startup is in progress"""
        return self._is_starting
    
    @property
    def is_ready(self) -> bool:
        """Check if startup is complete and successful"""
        return self.state.phase == StartupPhase.COMPLETE
    
    async def wait_for_startup(self, timeout: float = 60.0) -> bool:
        """Wait for startup to complete"""
        try:
            await asyncio.wait_for(
                self._startup_complete.wait(),
                timeout=timeout
            )
            return self.is_ready
        except asyncio.TimeoutError:
            return False
    
    def get_state(self) -> Dict[str, Any]:
        """Get current startup state"""
        return self.state.to_dict()
    
    def get_progress(self) -> Dict[str, Any]:
        """Get startup progress summary"""
        total_steps = len(self.state.steps)
        completed_steps = sum(1 for s in self.state.steps if s.completed)
        failed_steps = sum(1 for s in self.state.steps if not s.completed and s.error)
        
        return {
            "phase": self.state.phase.value,
            "progress_percent": self.state.progress_percent,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "mode": self.state.mode,
            "is_ready": self.is_ready
        }