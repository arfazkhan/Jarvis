"""
Think Tool Handler
------------------
Handles the 'think' tool - internal reasoning scratchpad for LLM.
Logs reasoning to audit file for debugging and transparency.
"""

import os
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any


class ThinkToolHandler:
    """
    Handles think tool - logs reasoning to audit file (non-blocking).
    
    The think tool is used by the LLM for internal reasoning before
    making safety-critical decisions. Output is NOT shown to users
    but logged for debugging and audit purposes.
    """
    
    def __init__(self, log_dir: str = "agent/logs"):
        """
        Initialize ThinkToolHandler with logging setup.
        
        Args:
            log_dir: Directory for log files (created if doesn't exist)
        """
        # Ensure logs directory exists
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "reasoning_audit.log"
        
        # Setup dedicated logger for reasoning audit
        self.logger = logging.getLogger("arvis.reasoning")
        self.logger.setLevel(logging.DEBUG)
        
        # Avoid duplicate handlers
        if not self.logger.handlers:
            # File handler for persistent logging
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            
            # Format: timestamp, level, message
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        print(f"[ThinkToolHandler] Initialized. Audit log: {self.log_file}")
    
    def execute(self, reasoning: str) -> Dict[str, Any]:
        """
        Execute think tool - log reasoning and return immediately.
        
        Args:
            reasoning: The LLM's internal reasoning string
            
        Returns:
            dict with success status and action_taken=False (no side effects)
        """
        try:
            # Log asynchronously to avoid blocking
            self._log_async(reasoning)
            
            return {
                "success": True,
                "action_taken": False,
                "message": "Reasoning logged to audit trail"
            }
            
        except Exception as e:
            self.logger.error(f"Think tool error: {e}")
            return {
                "success": False,
                "action_taken": False,
                "error": str(e)
            }
    
    def _log_async(self, reasoning: str) -> None:
        """
        Log reasoning asynchronously (non-blocking).
        
        Args:
            reasoning: The reasoning text to log
        """
        def _do_log():
            # Add separator for readability
            self.logger.info("=" * 60)
            self.logger.info(f"THINK: {reasoning}")
            self.logger.info("=" * 60)
        
        # Run in background thread to avoid blocking
        thread = threading.Thread(target=_do_log, daemon=True)
        thread.start()
    
    def get_recent_thoughts(self, count: int = 10) -> list:
        """
        Retrieve recent thoughts from audit log (for debugging).
        
        Args:
            count: Number of recent entries to retrieve
            
        Returns:
            List of recent reasoning entries
        """
        try:
            if not self.log_file.exists():
                return []
            
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Get last N entries (3 lines per entry: separator, thought, separator)
            thoughts = []
            current_thought = []
            
            for line in lines:
                if "THINK:" in line:
                    # Extract thought content
                    thought = line.split("THINK:")[1].strip() if "THINK:" in line else line.strip()
                    thoughts.append(thought)
            
            return thoughts[-count:]
            
        except Exception as e:
            self.logger.error(f"Error reading thoughts: {e}")
            return []
