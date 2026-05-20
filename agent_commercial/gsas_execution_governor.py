import logging
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)

class GovernanceTier(str, Enum):
    LOW_RISK = "LOW_RISK"              # Operator can action immediately, low consequence
    REVIEW_RECOMMENDED = "REVIEW_RECOMMENDED"  # Operator should review before actioning
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"    # FM sign-off required before actioning

class GSASExecutionGovernor:
    """
    Evaluates BMS actions and their simulated GSAS impacts to determine the required execution governance tier.
    """

    @classmethod
    def classify_action_risk(cls, action: Dict[str, Any], simulation_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classifies the risk of an action and determines its governance tier based on:
        - Comfort risk
        - GSAS score impact
        - Action type
        """
        action_type = action.get("type", "")
        
        if not action_type:
            return {
                "tier": GovernanceTier.APPROVAL_REQUIRED.value,
                "reason": "Action 'type' field is missing or empty. Cannot classify risk — defaulting to human-in-the-loop."
            }
        
        # 1. Check GSAS simulation warnings (Critical overrides)
        warnings = simulation_result.get("warnings", {})
        if warnings.get("energy_critical") or warnings.get("water_critical"):
            return {
                "tier": GovernanceTier.APPROVAL_REQUIRED.value,
                "reason": "Simulation projects critical drop in E or W GSAS category score."
            }

        if simulation_result.get("score_delta", 0) < 0:
            return {
                "tier": GovernanceTier.APPROVAL_REQUIRED.value,
                "reason": "Simulation projects an overall drop in GSAS score."
            }

        # 2. Check Action Type Rules
        if "setpoint" in action_type:
            params = action.get("params", {})
            # Check magnitude of setpoint change if available
            delta = 0.0
            if "value_delta" in action:
                delta = abs(float(action.get("value_delta", 0)))
            elif "temp_range_c" in params:
                # Mock delta check
                delta = 1.0 
            else:
                delta = 0.5
                
            if delta <= 1.0:
                return {
                    "tier": GovernanceTier.LOW_RISK.value,
                    "reason": "Low risk: Operator can action immediately. Setpoint change ≤ 1.0°C."
                }
            else:
                return {
                    "tier": GovernanceTier.REVIEW_RECOMMENDED.value,
                    "reason": "Review recommended before actioning. Setpoint change > 1.0°C."
                }
                
        elif "schedule" in action_type:
            if not action.get("during_occupancy", False):
                return {
                    "tier": GovernanceTier.LOW_RISK.value,
                    "reason": "Low risk: Operator can action immediately. Schedule reduction applies to unoccupied zones only."
                }
            else:
                return {
                    "tier": GovernanceTier.APPROVAL_REQUIRED.value,
                    "reason": "High risk: Schedule reduction during occupancy hours."
                }
                
        elif "staging" in action_type or "equipment" in action_type:
            return {
                "tier": GovernanceTier.APPROVAL_REQUIRED.value,
                "reason": "Medium/High risk: Equipment staging changes require FM oversight."
            }

        elif "ventilation" in action_type or "economizer" in action_type:
            return {
                "tier": GovernanceTier.REVIEW_RECOMMENDED.value,
                "reason": "Review recommended before actioning. Ventilation/Economizer tuning."
            }

        # Default fallback
        return {
            "tier": GovernanceTier.APPROVAL_REQUIRED.value,
            "reason": "Action type not explicitly classified. Defaulting to human-in-the-loop."
        }
