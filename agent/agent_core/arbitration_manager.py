import time
import threading
import logging
from enum import IntEnum
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

class Priority(IntEnum):
    """Priority levels for resource access."""
    CRITICAL = 100       # Emergency overrides
    USER_COMMAND = 90    # Direct user interaction
    SAFETY_LOCK = 80     # Safety systems
    MISSION_EXECUTION = 50 # Active missions
    AUTOMATION_RULE = 30   # Routine automations
    PROACTIVE_SUGGESTION = 10 # Background suggestions

@dataclass
class LockInfo:
    source: str
    priority: int
    expiration_time: float
    metadata: Dict

class ArbitrationManager:
    """
    Manages resource contention using a priority-based locking mechanism.
    Ensures high-priority tasks (User, Safety) can preempt lower-priority ones.
    """
    def __init__(self):
        self.locks: Dict[str, LockInfo] = {}
        self._lock_mutex = threading.RLock() # Thread-safety for lock table
        self.logger = logging.getLogger("ArbitrationManager")

    def request_lock(self, device_id: str, source: str, priority: int, duration: float = 5.0) -> bool:
        """
        Attempt to acquire a lock for a device.
        
        Args:
            device_id: The resource to lock.
            source: Name of the requester (e.g., "MissionExecutor").
            priority: Priority level (use Priority enum).
            duration: How long to hold the lock in seconds.
            
        Returns:
            bool: True if lock acquired, False otherwise.
        """
        with self._lock_mutex:
            now = time.time()
            current_lock = self.locks.get(device_id)

            # 1. Check if locked
            if current_lock:
                # Check expiration
                if now > current_lock.expiration_time:
                    self.logger.debug(f"Lock for {device_id} expired. Taking over.")
                    # Expired, we can take it
                    pass 
                elif priority > current_lock.priority:
                    # Preemption
                    self.logger.info(f"Preempting lock on {device_id}: {source} ({priority}) > {current_lock.source} ({current_lock.priority})")
                    # We can take it
                    pass
                elif priority == current_lock.priority and source == current_lock.source:
                    # Extending own lock
                    pass
                else:
                    # Denied
                    self.logger.debug(f"Lock denied for {device_id}: {source} ({priority}) <= {current_lock.source} ({current_lock.priority})")
                    return False

            # 2. Grant Lock
            self.locks[device_id] = LockInfo(
                source=source,
                priority=priority,
                expiration_time=now + duration,
                metadata={}
            )
            self.logger.debug(f"Lock granted for {device_id} to {source} (P:{priority}) for {duration}s")
            return True

    def release_lock(self, device_id: str, source: str) -> bool:
        """
        Release a lock if held by the source.
        """
        with self._lock_mutex:
            current_lock = self.locks.get(device_id)
            if not current_lock:
                return True # Already free
            
            # Only owner can release (unless expired, which is handled in request)
            # Or maybe we allow force release? For now, strict ownership.
            if current_lock.source == source:
                del self.locks[device_id]
                self.logger.debug(f"Lock released for {device_id} by {source}")
                return True
            
            # Check if expired, if so, clean up
            if time.time() > current_lock.expiration_time:
                del self.locks[device_id]
                return True

            return False

    def get_lock_status(self, device_id: str) -> Optional[Dict]:
        """Get current lock status for a device."""
        with self._lock_mutex:
            lock = self.locks.get(device_id)
            if not lock:
                return None
            
            # Check expiry on read
            if time.time() > lock.expiration_time:
                del self.locks[device_id]
                return None
                
            return {
                "source": lock.source,
                "priority": lock.priority,
                "remaining": lock.expiration_time - time.time()
            }
