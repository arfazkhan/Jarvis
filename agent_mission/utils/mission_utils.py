"""
Mission Utilities
-----------------
Utility functions for mission system including metric target parsing and validation.
"""

import re
from typing import Tuple, Optional, Callable

class MetricTargetParser:
    """
    Parses metric target strings and creates validation functions.
    
    Examples:
        "< 30 minutes" → validator(value): value < 30
        "> 0.8" → validator(value): value > 0.8
        "< 5 events" → validator(value): value < 5
    """
    
    @staticmethod
    def parse(target: str) -> Tuple[str, float, str]:
        """
        Parse target string into operator, threshold, and unit.
        
        Args:
            target: Target string (e.g., "< 30 minutes", "> 0.8")
        
        Returns:
            (operator, threshold, unit) tuple
            
        Raises:
            ValueError: If target format is invalid
        """
        # Pattern: operator threshold [unit]
        # Examples: "< 30 minutes", "> 0.8", "< 5 events"
        pattern = r'([<>]=?)\s*([0-9.]+)\s*([a-zA-Z]*)'
        match = re.match(pattern, target.strip())
        
        if not match:
            raise ValueError(f"Invalid target format: {target}")
        
        operator = match.group(1)
        threshold = float(match.group(2))
        unit = match.group(3) if match.group(3) else ""
        
        return (operator, threshold, unit)
    
    @staticmethod
    def create_validator(target: str) -> Callable[[float], bool]:
        """
        Create a validation function from target string.
        
        Args:
            target: Target string (e.g., "< 30", "> 0.8")
        
        Returns:
            Validator function that takes a value and returns True if target is met
        """
        operator, threshold, unit = MetricTargetParser.parse(target)
        
        if operator == "<":
            return lambda value: value < threshold
        elif operator == "<=":
            return lambda value: value <= threshold
        elif operator == ">":
            return lambda value: value > threshold
        elif operator == ">=":
            return lambda value: value >= threshold
        else:
            raise ValueError(f"Unknown operator: {operator}")
    
    @staticmethod
    def validate(target: str, value: float) -> bool:
        """
        Validate a value against a target.
        
        Args:
            target: Target string (e.g., "< 30 minutes")
            value: Value to validate
        
        Returns:
            True if value meets target, False otherwise
        """
        validator = MetricTargetParser.create_validator(target)
        return validator(value)


class MissionLogger:
    """Simple mission event logger"""
    
    @staticmethod
    def log_step_start(mission_id: str, step_id: str, action: str):
        print(f"[{mission_id}] Step started: {step_id} ({action})")
    
    @staticmethod
    def log_step_complete(mission_id: str, step_id: str, duration: float):
        print(f"[{mission_id}] Step completed: {step_id} ({duration:.2f}s)")
    
    @staticmethod
    def log_step_failed(mission_id: str, step_id: str, error: str):
        print(f"[{mission_id}] Step failed: {step_id} - {error}")
    
    @staticmethod
    def log_mission_start(mission_id: str, mission_type: str):
        print(f"[{mission_id}] Mission started: {mission_type}")
    
    @staticmethod
    def log_mission_complete(mission_id: str, duration: float):
        print(f"[{mission_id}] Mission completed ({duration:.2f}s)")
