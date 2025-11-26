"""
Plan Rewriter
-------------
Orchestrates the adaptive planning process.
1. Takes a raw plan.
2. Applies preferences via AdaptivePlanEngine.
3. Validates the result via SafetyValidator.
4. Ensures no safety violations are introduced.
"""

from typing import Dict, Any, List, Optional
from agent_plan.adaptive_plan.adaptive_plan_engine import AdaptivePlanEngine
from agent_plan.safety_validator import SafetyValidator

class PlanRewriter:
    def __init__(self, adaptive_engine: AdaptivePlanEngine, validator: SafetyValidator):
        self.adaptive_engine = adaptive_engine
        self.validator = validator

    def rewrite_plan(self, raw_plan: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Rewrite a plan based on preferences, ensuring safety.
        """
        context = context or {}
        
        # 1. Adapt
        adapted_plan = self.adaptive_engine.adapt_plan(raw_plan)
        
        # 2. Validate Adapted Plan
        steps = adapted_plan.get("steps", [])
        validated_steps, errors = self.validator.validate_plan(steps, context)
        
        if errors:
            print(f"[PlanRewriter] Safety violation in adapted plan: {errors}")
            
            # 3. Fallback to Raw Plan if Adapted is unsafe
            # Check if raw plan was safe
            raw_steps = raw_plan.get("steps", [])
            _, raw_errors = self.validator.validate_plan(raw_steps, context)
            
            if not raw_errors:
                print("[PlanRewriter] Reverting to raw plan.")
                # We return raw plan but maybe mark it as "adaptation_failed"
                raw_plan["metadata"] = raw_plan.get("metadata", {})
                raw_plan["metadata"]["adaptation_error"] = errors
                return raw_plan
            else:
                print("[PlanRewriter] Raw plan also unsafe. Returning empty plan.")
                return {"steps": [], "error": "Unsafe plan", "details": raw_errors}
                
        # 4. Return Safe Adapted Plan
        adapted_plan["steps"] = validated_steps
        return adapted_plan
