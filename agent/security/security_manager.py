"""
Security Manager
----------------
Handles PIN verification and identity confirmation for critical operations.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta


class SecurityManager:
    """
    Manages security verification for critical ARVIS operations.
    
    Critical operations requiring PIN:
    - Delete/destroy/reset commands
    - Developer mode access
    - Bypass safety commands  
    - Lock/unlock commands
    - Routine deletion
    - Factory reset
    """
    
    # Operations that require PIN verification
    CRITICAL_KEYWORDS = [
        "delete", "destroy", "reset", "factory", "remove all",
        "developer", "admin", "bypass", "override",
        "unlock", "disable alarm", "disable security",
        "clear", "erase", "wipe"
    ]
    
    def __init__(self, config_path: str = "agent/security/security_config.json"):
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load or initialize config
        self.config = self._load_config()
        
        # Track failed attempts
        self.failed_attempts: Dict[str, int] = {}
        self.lockout_until: Dict[str, datetime] = {}
        
        # Session-based verification (valid for 5 minutes after correct PIN)
        self.verified_sessions: Dict[str, datetime] = {}
        self.session_duration = timedelta(minutes=5)
        
        print(f"[SecurityManager] Initialized. PIN configured: {self.is_pin_configured()}")
    
    def _load_config(self) -> dict:
        """Load security configuration"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Default config
        return {
            "pin_hash": None,  # SHA-256 hash of PIN
            "max_attempts": 3,
            "lockout_minutes": 15,
            "require_pin_for_critical": True
        }
    
    def _save_config(self):
        """Save security configuration"""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def _hash_pin(self, pin: str) -> str:
        """Hash a PIN using SHA-256"""
        return hashlib.sha256(pin.encode()).hexdigest()
    
    def is_pin_configured(self) -> bool:
        """Check if a PIN has been set up"""
        return self.config.get("pin_hash") is not None
    
    def setup_pin(self, new_pin: str) -> dict:
        """
        Set up or change the security PIN.
        PIN must be 4-8 digits.
        """
        # Validate PIN format
        if not new_pin.isdigit():
            return {"success": False, "error": "PIN must contain only digits"}
        
        if len(new_pin) < 4 or len(new_pin) > 8:
            return {"success": False, "error": "PIN must be 4-8 digits"}
        
        # Store hashed PIN
        self.config["pin_hash"] = self._hash_pin(new_pin)
        self._save_config()
        
        print(f"[SecurityManager] PIN configured successfully")
        return {"success": True, "message": "Security PIN configured"}
    
    def verify_pin(self, pin: str, session_id: str = "default") -> dict:
        """
        Verify a PIN attempt.
        Returns success status and creates a verified session if correct.
        """
        # Check lockout
        if session_id in self.lockout_until:
            if datetime.now() < self.lockout_until[session_id]:
                remaining = (self.lockout_until[session_id] - datetime.now()).seconds // 60
                return {
                    "success": False, 
                    "error": f"Account locked. Try again in {remaining} minutes.",
                    "locked": True
                }
            else:
                # Lockout expired
                del self.lockout_until[session_id]
                self.failed_attempts[session_id] = 0
        
        # Check if PIN is configured
        if not self.is_pin_configured():
            return {"success": False, "error": "No PIN configured. Set up a PIN first."}
        
        # Verify PIN
        if self._hash_pin(pin) == self.config["pin_hash"]:
            # Success - create verified session
            self.verified_sessions[session_id] = datetime.now()
            self.failed_attempts[session_id] = 0
            print(f"[SecurityManager] PIN verified for session: {session_id}")
            return {
                "success": True, 
                "message": "PIN verified. Session active for 5 minutes.",
                "session_valid_until": (datetime.now() + self.session_duration).isoformat()
            }
        else:
            # Failed attempt
            self.failed_attempts[session_id] = self.failed_attempts.get(session_id, 0) + 1
            attempts_left = self.config["max_attempts"] - self.failed_attempts[session_id]
            
            if attempts_left <= 0:
                # Lock out
                self.lockout_until[session_id] = datetime.now() + timedelta(
                    minutes=self.config["lockout_minutes"]
                )
                print(f"[SecurityManager] Session {session_id} locked out")
                return {
                    "success": False,
                    "error": f"Too many failed attempts. Locked for {self.config['lockout_minutes']} minutes.",
                    "locked": True
                }
            
            return {
                "success": False,
                "error": f"Incorrect PIN. {attempts_left} attempts remaining."
            }
    
    def is_session_verified(self, session_id: str = "default") -> bool:
        """Check if a session is currently verified"""
        if session_id not in self.verified_sessions:
            return False
        
        # Check if session expired
        if datetime.now() - self.verified_sessions[session_id] > self.session_duration:
            del self.verified_sessions[session_id]
            return False
        
        return True
    
    def requires_verification(self, command: str) -> bool:
        """
        Check if a command requires PIN verification.
        """
        if not self.config.get("require_pin_for_critical", True):
            return False
        
        command_lower = command.lower()
        
        for keyword in self.CRITICAL_KEYWORDS:
            if keyword in command_lower:
                return True
        
        return False
    
    def get_verification_prompt(self, command: str) -> str:
        """Get the appropriate verification prompt for a command"""
        if not self.is_pin_configured():
            return "🔐 This action requires security verification, but no PIN is configured. Please set up a security PIN first using the command: 'set security PIN to XXXX'"
        
        return f"🔐 This action requires PIN verification. Please say or type your security PIN to proceed with: {command[:50]}..."
    
    def invalidate_session(self, session_id: str = "default"):
        """Manually invalidate a session"""
        if session_id in self.verified_sessions:
            del self.verified_sessions[session_id]
            print(f"[SecurityManager] Session {session_id} invalidated")


# Singleton instance
_security_manager: Optional[SecurityManager] = None

def get_security_manager() -> SecurityManager:
    """Get or create the singleton SecurityManager instance"""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager
