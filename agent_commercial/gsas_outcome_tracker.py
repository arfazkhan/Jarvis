import logging
import json
import os
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

class GSASOutcomeTracker:
    """
    Tracks the execution outcomes of GSAS-related BMS actions.
    Records FM decisions (approve/reject), execution success, and eventual impact.
    Serves as the memory layer for the swarm to learn which actions are effective.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self.outcomes_file = os.path.join(os.path.dirname(__file__), "..", "learning", "gsas_outcomes.json")
        self._history = self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.outcomes_file):
            try:
                with open(self.outcomes_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load GSAS outcomes: {e}")
        return []

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(self.outcomes_file), exist_ok=True)
            with open(self.outcomes_file, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save GSAS outcomes: {e}")

    def record_action_outcome(self, action: Dict[str, Any], decision: str, notes: str = "") -> Dict[str, Any]:
        """
        Record the FM's decision on a proposed action (APPROVED, REJECTED, MODIFIED).
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "action_type": action.get("type", "unknown"),
            "action": action,
            "decision": decision.upper(),
            "notes": notes
        }
        
        if self.db:
            try:
                # Assuming an asynchronous save_outcome method exists on the DB instance
                # If synchronous, remove await in the actual handler implementation
                pass # Implementation would depend on the actual DB schema
            except Exception as e:
                logger.error(f"Failed to save outcome to DB: {e}")
                
        self._history.append(record)
        self._save_history()
        return {"status": "recorded", "record": record}

    def get_success_rates(self, action_type: str = None) -> Dict[str, Any]:
        """
        Calculate the approval rate for actions. The Memory Agent uses this
        to avoid suggesting actions the FM consistently rejects.
        """
        history = self._history
        if self.db:
            try:
                pass # implementation to fetch from DB
            except Exception:
                pass
                
        if action_type:
            history = [r for r in history if r["action_type"] == action_type]
            
        if not history:
            return {
                "action_type": action_type or "all", 
                "total_proposed": 0, 
                "approved": 0,
                "rejected": 0,
                "approval_rate": 0.0
            }
            
        approved = sum(1 for r in history if r["decision"] == "APPROVED")
        rejected = sum(1 for r in history if r["decision"] == "REJECTED")
        
        return {
            "action_type": action_type or "all",
            "total_proposed": len(history),
            "approved": approved,
            "rejected": rejected,
            "approval_rate": round(approved / len(history), 2) if history else 0.0
        }

    def get_adjusted_confidence(self, action_type: str, criterion_id: str, base_confidence: float = 0.8) -> float:
        """
        Calculates a Bayesian confidence score based on historical approval rates.
        If an action type is frequently approved for a specific criterion, confidence increases.
        If frequently rejected, confidence decreases.
        """
        # Filter history for this action_type and optionally criterion_id
        # Assuming action might have target_criterion
        relevant_history = [
            r for r in self._history 
            if r["action_type"] == action_type and 
               (not criterion_id or r.get("action", {}).get("target_criterion") == criterion_id)
        ]
        
        if not relevant_history:
            return base_confidence
            
        approved = sum(1 for r in relevant_history if r["decision"] == "APPROVED")
        total = len(relevant_history)
        
        # Simple Bayesian update: (Prior Weight * Prior Success + Observed Successes) / (Prior Weight + Observed Total)
        # Assuming a prior weight of 5 past experiences at the base_confidence
        prior_weight = 5.0
        prior_success = base_confidence * prior_weight
        
        adjusted_confidence = (prior_success + approved) / (prior_weight + total)
        return round(adjusted_confidence, 2)
