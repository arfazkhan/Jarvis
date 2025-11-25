"""
Safety Validator
----------------
Gatekeeper for all autonomous actions.
Checks:
1. Rate Limits (500ms rule)
2. Conflicts (Same device, different actions)
3. Risk Classification (High risk requires approval - mocked for now)
4. Context Mismatch (e.g., AC on while windows open)
"""

import time
from typing import List, Dict, Any, Tuple

from config.settings import get_config

CONFIG = get_config("planning")
SAFETY_CONFIG = CONFIG.get("safety", {})

class SafetyValidator:
    def __init__(self):
        self.last_action_time: Dict[str, float] = {} # device_id -> timestamp
        self.high_risk_devices = SAFETY_CONFIG.get("high_risk_devices", ["locks", "alarms", "garage"])
        
    def validate_plan(self, plan: List[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Validate a list of planned actions.
        Returns: (validated_plan, errors)
        """
        validated_plan = []
        errors = []
        
        # 1. Conflict Detection (Simple: Duplicate targets in same plan)
        targets_seen = set()
        
        for step in plan:
            action = step.get("action")
            params = step.get("params", {})
            target = params.get("device") or params.get("target")
            
            if not target:
                # Allow actions without specific target (e.g., system notifications)
                validated_plan.append(step)
                continue
                
            # Check for conflicts within the plan
            if target in targets_seen:
                # In a real DAG, parallel actions on same target are bad. 
                # Sequential is fine, but for now we flag as potential conflict if simple list.
                errors.append(f"Conflict: Multiple actions for {target} in same plan.")
                continue
            targets_seen.add(target)
            
            # 2. Risk Check
            if target in self.high_risk_devices:
                # For MVP, we might just warn or require a specific flag
                # step["requires_approval"] = True
                pass
                
            # 3. Context Check (Mocked)
            # if target == "ac" and context.get("windows_open"):
            #    errors.append("Cannot turn on AC while windows are open.")
            #    continue
            
            validated_plan.append(step)
            
        return validated_plan, errors

    def check_rate_limit(self, device_id: str) -> bool:
        """Return True if safe to proceed (not rate limited)"""
        now = time.time()
        last = self.last_action_time.get(device_id, 0)
        if now - last < 0.5: # 500ms limit
            return False
        self.last_action_time[device_id] = now
        return True
