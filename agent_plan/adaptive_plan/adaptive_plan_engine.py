"""
Adaptive Plan Engine
--------------------
Modifies raw plans based on learned user preferences.
"""

from typing import Dict, Any, List
from agent_preferences.preference_store import PreferenceStore
from agent_plan.adaptive_plan.modifier_rules import MODIFIERS

class AdaptivePlanEngine:
    def __init__(self, preference_store: PreferenceStore):
        self.store = preference_store

    def adapt_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply preferences to a plan.
        Returns a new modified plan.
        """
        # Deep copy to avoid mutating original
        import copy
        modified_plan = copy.deepcopy(plan)
        
        steps = modified_plan.get("steps", [])
        
        for step in steps:
            action = step.get("action")
            
            # Determine category for this action
            category = self._get_category_for_action(action)
            if not category:
                continue
                
            # Fetch preferences for this category
            prefs = self.store.get_all_by_category(category)
            if not prefs:
                continue
                
            # Apply modifiers
            modifier = MODIFIERS.get(action)
            if modifier:
                modifier(step, prefs)
                
        modified_plan["is_adapted"] = True
        return modified_plan

    def _get_category_for_action(self, action: str) -> str:
        if action == "set_light": return "lighting"
        if action in ["set_climate", "set_ac"]: return "climate"
        if action == "play_media": return "media"
        return None
