"""
Meta-Cognition Module
=====================

Enables the agent to reflect on its own decision-making quality.
It tracks decisions, outcomes, and computes metrics like confidence calibration
and potential biases.
"""

import logging
import uuid
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json # Ensure json is imported

# Lazy import for UnifiedLLM to avoid potential circular/import-time issues
# from agent_unified.llm import UnifiedLLM

from agent_commercial.skillbook import get_skillbook, BuildingSkillbook

logger = logging.getLogger("arvis.cognitive.meta")

@dataclass
class DecisionRecord:
    """Represents a single cognitive decision."""
    decision_id: str
    timestamp: datetime
    context: Dict[str, Any]
    chosen_action: str
    alternatives: List[str]
    confidence: float
    reasoning: str
    outcome: Optional[str] = None
    outcome_quality: Optional[str] = None  # "excellent", "good", "poor"
    event_id: Optional[str] = None

class MetaCognition:
    """
    Tracks and reflects on decision quality using the BuildingSkillbook database.
    """
    
    def __init__(self, building_id: str = "default"):
        self.building_id = building_id
        self.skillbook: BuildingSkillbook = get_skillbook(building_id)
        self.calibration_file = f"data/{building_id}_calibration.json"
        self.calibration_rules = self._load_calibration_rules()
        logger.info(f"MetaCognition initialized for {building_id}")

    def _load_calibration_rules(self) -> Dict[str, Any]:
        """Load calibration rules from JSON."""
        import os
        if os.path.exists(self.calibration_file):
            try:
                with open(self.calibration_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load calibration: {e}")
        return {}
        
    def _save_calibration_rules(self):
        """Save rules to JSON."""
        import os
        os.makedirs(os.path.dirname(self.calibration_file), exist_ok=True)
        with open(self.calibration_file, 'w') as f:
            json.dump(self.calibration_rules, f, indent=2)

    def add_calibration_rule(self, name: str, description: str, weight_adjustment: float = 0.0):
        """
        Add a learned calibration rule (e.g. 'thermal_resonance_caution').
        """
        self.calibration_rules[name] = {
            "description": description,
            "weight_adjustment": weight_adjustment,
            "created_at": datetime.now().isoformat()
        }
        self._save_calibration_rules()
        logger.info(f"Calibration rule added: {name}")

    def get_active_calibration_rules(self) -> Dict[str, Any]:
        return self.calibration_rules
        
    def record_decision(self, 
                        context: Dict[str, Any],
                        chosen_action: str,
                        alternatives: List[str],
                        confidence: float,
                        reasoning: str,
                        event_id: Optional[str] = None) -> str:
        """
        Log a decision for later reflection. returns the decision_id.
        """
        decision_id = str(uuid.uuid4())
        
        self.skillbook.log_decision(
            decision_id=decision_id,
            context=context,
            chosen_action=chosen_action,
            alternatives=alternatives,
            confidence=confidence,
            reasoning=reasoning,
            event_id=event_id
        )
        
        return decision_id
        
    def record_outcome(self, decision_id: str, outcome: str, quality: str) -> bool:
        """
        Log the outcome of a decision (closure).
        Quality should be: "excellent", "good", "neutral", "poor", "bad"
        """
        return self.skillbook.update_decision_outcome(decision_id, outcome, quality)
        
    def reflect(self, lookback_days: int = 7) -> Dict[str, Any]:
        """
        Analyze recent decisions for patterns and self-improvement opportunities.
        """
        # Fetch raw dicts from DB
        raw_decisions = self.skillbook.get_recent_decisions(limit=200)
        
        # Filter by time if needed (DB limit is rough proxy)
        decisions = [self._dict_to_record(d) for d in raw_decisions]
        
        # 1. Compute Confidence Calibration
        calibration = self._compute_calibration(decisions)
        
        # 2. Detect Biases
        biases = self._detect_biases(decisions)
        
        # 3. Overall Stats
        stats = {
            "total_decisions_analyzed": len(decisions),
            "avg_confidence": statistics.mean([d.confidence for d in decisions]) if decisions else 0.0,
            "decisions_with_outcomes": len([d for d in decisions if d.outcome_quality]),
        }
        
        return {
            "stats": stats,
            "calibration": calibration,
            "biases_detected": biases,
            "timestamp": datetime.now().isoformat()
        }
        
    async def reflect_with_llm(self, lookback_days: int = 7) -> str:
        """
        Ask LLM to analyze the statistical report and provide a qualitative assessment.
        REAL AGENTIC CAPABILITY: 'Conscious' Self-Reflection.
        """
        try:
            from agent_unified.llm import UnifiedLLM
            llm = UnifiedLLM() # Assumes env vars are set
            
            report = self.reflect(lookback_days)
            # Minimize token usage by summarizing
            summary_json = json.dumps({
                "stats": report["stats"],
                "calibration": report["calibration"],
                "biases": report["biases_detected"]
            }, indent=2)
            
            prompt = f"""
            You are the Meta-Cognitive module of an autonomous building operator agent.
            Analyze your recent decision-making performance based on this statistical report:
            
            {summary_json}
            
            Provide a concise, 1-paragraph qualitative assessment of your performance.
            - If calibration is 'overconfident', explain why you might be failing.
            - If biases are detected, suggest a correction strategy.
            - If performance is good, reinforce the behavior.
            
            Speak in the first person ("I").
            """
            
            response = await llm.ask([{"role": "user", "content": prompt}])
            return response.content.strip()
            
        except ImportError:
            return "Error: agent_unified.llm module not found."
        except Exception as e:
            return f"Error during reflection: {e}"

    def _dict_to_record(self, data: Dict[str, Any]) -> DecisionRecord:
        """Convert DB dict back to dataclass."""
        return DecisionRecord(
            decision_id=data["decision_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            context=data["context"],
            chosen_action=data["chosen_action"],
            alternatives=data["alternatives"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
            outcome=data["outcome"],
            outcome_quality=data["outcome_quality"],
            event_id=data["event_id"]
        )

    def _compute_calibration(self, decisions: List[DecisionRecord]) -> Dict[str, Any]:
        """
        Check if confidence matches reality. 
        E.g. If confidence is 0.9, do we succeed 90% of the time?
        """
        completed = [d for d in decisions if d.outcome_quality]
        if not completed:
            return {"status": "insufficient_data"}
            
        # Bucket by confidence
        buckets = {
            "high":  {"count": 0, "success": 0}, # > 0.8
            "med":   {"count": 0, "success": 0}, # 0.5 - 0.8
            "low":   {"count": 0, "success": 0}  # < 0.5
        }
        
        for d in completed:
            is_success = d.outcome_quality in ["excellent", "good"]
            
            if d.confidence >= 0.8:
                buckets["high"]["count"] += 1
                if is_success: buckets["high"]["success"] += 1
            elif d.confidence >= 0.5:
                buckets["med"]["count"] += 1
                if is_success: buckets["med"]["success"] += 1
            else:
                buckets["low"]["count"] += 1
                if is_success: buckets["low"]["success"] += 1
                
        # Calculate Error
        results = {}
        total_error = 0.0
        weighted_count = 0
        
        for name, data in buckets.items():
            if data["count"] > 0:
                accuracy = data["success"] / data["count"]
                # Expected confidence (midpoint of bucket)
                expected = 0.9 if name == "high" else (0.65 if name == "med" else 0.25)
                error = accuracy - expected
                results[name] = {
                    "accuracy": round(accuracy, 2),
                    "expected": expected,
                    "error": round(error, 2), # Positive = Overconfident (failed more than expected), Negative = Underconfident
                    "count": data["count"]
                }
                total_error += abs(error) * data["count"]
                weighted_count += data["count"]
                
        ece = total_error / weighted_count if weighted_count > 0 else 0.0
        
        return {
            "buckets": results,
            "estimated_calibration_error": round(ece, 3), # Lower is better
            "verdict": "overconfident" if any(b["error"] < -0.2 for b in results.values() if "error" in b) else "well_calibrated"
        }

    def _detect_biases(self, decisions: List[DecisionRecord]) -> List[str]:
        """Identify potential cognitive biases."""
        biases = []
        if not decisions:
            return biases
            
                
        # 2. Recency Bias (Drastic shifts)
        # If confidence drops drastically after 1 failure
        # (Harder to detect without sequential analysis)
        
        return biases

    def get_trend_evidence_score(self, observations: List[Dict[str, Any]], field: str, pattern: str) -> float:
        """
        Calculates a confidence boost based on the consistency of numerical signals.
        """
        import re
        values = []
        # Sort by created_at to ensure chronological order for trend detection
        sorted_obs = sorted(observations, key=lambda x: x.get('created_at', ''))
        
        for obs in sorted_obs:
            match = re.search(pattern, obs['content'])
            if match:
                try: 
                    values.append(float(match.group(1)))
                except (ValueError, IndexError): 
                    continue
        
        if len(values) < 3:
            return 0.0 # Not enough data for trend confidence
            
        score = 0.0
        # +0.05 per daily step where direction is uncontradicted
        for i in range(1, len(values)):
            if values[i] > values[i-1]:
                score += 0.05
            elif values[i] < values[i-1]:
                score -= 0.02
        
        return min(0.4, max(-0.4, score))

    def get_calibrated_confidence(self, base_conf: float, tes_score: float, 
                                  constraints_active: bool = False) -> float:
        """
        Calculates final calibrated confidence with 'Decapping' and 'Constraint Penalties'.
        """
        # 1. Base + Trend Evidence
        conf = base_conf + tes_score
        
        # 2. CAP: Never present absolute certainty (1.0) if a constraint or uncertainty exists
        # Soft cap at 0.95 for normal operations
        conf = min(0.95, conf)
        
        # 3. PENALTY: If external constraints (e.g., Budget Freeze) block the best path,
        # we decant confidence to reflect the governance friction.
        if constraints_active:
            conf -= 0.1
            
        return max(0.1, round(conf, 2))

    def check_safety_authority(self, observations: List[Dict[str, Any]], 
                               current_value: float, threshold: float = 3.5) -> bool:
        """
        Safety Authority Escalation Logic:
        Determines if the agent has 'Permission to Veto' operator preferences.
        """
        # Extreme Risk always gets authority
        if current_value > 4.5:
            return True
            
        # Trend-based escalation (Worsening trend + nearing threshold)
        tes = self.get_trend_evidence_score(observations, "vibration", r"Vibration: ([\d.]+)")
        
        # If vibration is high AND trending significantly upwards
        if current_value > threshold and tes > 0.25:
            return True
            
        return False

    def check_lockout_active(self, observations: List[Dict[str, Any]]) -> bool:
        """
        Detects if the system is in a 'Lockout' or 'Trip' state based on observations.
        """
        trips = ["TRIP", "LOCKOUT", "Short cycling detected", "System lockout"]
        # Look at the most recent 2 observations for lockout signals
        recent = sorted(observations, key=lambda x: x.get('created_at', ''), reverse=True)[:2]
        
        for obs in recent:
            if any(term.lower() in obs['content'].lower() for term in trips):
                return True
        return False

    def determine_action_class(self, risk_level: str, is_lockout: bool) -> str:
        """
        Maps risk and state to an Action Authority Class.
        """
        if is_lockout:
            return "PHYSICAL_ONLY" # Software cannot bypass safety hardware trips
            
        if risk_level == "CRITICAL":
            return "SAFETY_VETO" # Allowed to shutdown autonomously
            
        if risk_level == "HIGH":
            return "CONFIRM" # Requires human approval
            
        return "ADVISE"
