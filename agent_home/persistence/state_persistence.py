"""
State Persistence Layer

Handles saving and loading state to/from disk.
"""

import json
import os
from typing import Dict, Any
from datetime import datetime


class StatePersistence:
    """Manage state persistence to disk."""
    
    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = state_file
        self.ensure_directory()
    
    def ensure_directory(self):
        """Ensure data directory exists."""
        directory = os.path.dirname(self.state_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
    
    def save_state(self, state: Dict[str, Any]) -> bool:
        """
        Save state to disk with atomic write.
        
        Returns:
            bool: True if successful
        """
        if self.state_file == ":memory:":
            return True

        try:
            # Write to temp file first (atomic)
            temp_file = f"{self.state_file}.tmp"
            
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force disk write
            
            # Atomic rename
            os.replace(temp_file, self.state_file)
            
            print(f"[Persistence] State saved to {self.state_file}")
            return True
            
        except Exception as e:
            print(f"[Persistence] Error saving state: {e}")
            return False
    
    def load_state(self) -> Dict[str, Any]:
        """
        Load state from disk.
        
        Returns:
            dict: Loaded state or default state if file doesn't exist
        """
        if self.state_file == ":memory:":
            return self.get_default_state()

        if not os.path.exists(self.state_file):
            print(f"[Persistence] No state file found, using defaults")
            return self.get_default_state()
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            print(f"[Persistence] State loaded from {self.state_file}")
            return state
            
        except json.JSONDecodeError as e:
            print(f"[Persistence] Corrupted state file: {e}")
            
            # Try to recover from backup
            backup = self.load_backup()
            if backup:
                return backup
            
            print(f"[Persistence] Using default state")
            return self.get_default_state()
            
        except Exception as e:
            print(f"[Persistence] Error loading state: {e}")
            return self.get_default_state()
    
    def create_backup(self) -> bool:
        """Create backup of current state file."""
        if not os.path.exists(self.state_file):
            return False
        
        try:
            backup_file = f"{self.state_file}.backup"
            
            with open(self.state_file, 'r') as src:
                with open(backup_file, 'w') as dst:
                    dst.write(src.read())
            
            print(f"[Persistence] Backup created: {backup_file}")
            return True
            
        except Exception as e:
            print(f"[Persistence] Error creating backup: {e}")
            return False
    
    def load_backup(self) -> Dict[str, Any]:
        """Load state from backup file."""
        backup_file = f"{self.state_file}.backup"
        
        if not os.path.exists(backup_file):
            return None
        
        try:
            with open(backup_file, 'r') as f:
                state = json.load(f)
            
            print(f"[Persistence] Loaded from backup")
            return state
            
        except Exception as e:
            print(f"[Persistence] Backup also corrupted: {e}")
            return None
    
    def get_default_state(self) -> Dict[str, Any]:
        """Get default empty state."""
        return {
            "version": 1,
            "devices": {},
            "routines": {},
            "history": [],
            "last_updated": datetime.now().isoformat()
        }
