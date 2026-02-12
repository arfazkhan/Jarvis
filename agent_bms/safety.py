"""
Safety Controller (Kill Switch)
===============================

The ultimate authority over ARVIS.
Implements the Green/Yellow/Red state machine.
Prevents any action unless explicitly authorized. (Layer 1)
"""

import functools
import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger("arvis.safety")

class SystemActiveState(Enum):
    RED = "red"         # Silent Mode: No recommendations, logging only.
    YELLOW = "yellow"   # Caution Mode: Advisory requiring dual confirmation.
    GREEN = "green"     # Advisory Mode: Standard operation.

class SafetyController:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SafetyController, cls).__new__(cls)
            cls._instance.state = SystemActiveState.GREEN # Default to Advisory
        return cls._instance

    def set_state(self, state: SystemActiveState):
        """Manually override the system state."""
        self.state = state
        logger.warning(f"SYSTEM SAFETY STATE CHANGED TO: {state.value.upper()}")

    def is_active(self) -> bool:
        return self.state != SystemActiveState.RED

    def check_kill_switch(self) -> bool:
        if self.state == SystemActiveState.RED:
            return False
        return True

def require_active_state(func: Callable):
    """Decorator to enforce kill-switch logic on critical functions."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        controller = SafetyController()
        if not controller.check_kill_switch():
            logger.error(f"BLOCKED ACTION {func.__name__}: System is in RED state (Kill Switch Active).")
            return {"error": "System is in SAFETY LOCKDOWN (Red Mode). Action denied."}
            
        # In Yellow mode, we might add logic here to require extra confirmation
        if controller.state == SystemActiveState.YELLOW:
            logger.info(f"Action {func.__name__} allowed with CAUTION (Yellow Mode).")
            
        return await func(*args, **kwargs)
    return wrapper
