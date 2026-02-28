"""
Trust Calibrator
================

Analyzes the performance of recommendations and trust signals from operators.
Calculates calibration scores to indicate how honest the AI's confidence is.

Capabilities:
1. Adoption Rate tracking (% of followed recommendations).
2. Accuracy tracking (When followed, was it good?).
3. Confidence Calibration (Actual success vs. stated confidence).
4. Reliability Heatmap (Identifying weak spots).
"""

import logging
import json
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger("arvis.advisory.trust")

class TrustCalibrator:
    """
    Evaluates the 'Trustworthiness' of the Advisor.
    Maintains metrics on adoption and accuracy.
    """
    
    def __init__(self, recommendation_tracker: Any):
        self.tracker = tracker = recommendation_tracker
    
    async def calculate_trust_metrics(self, window_days: int = 30) -> Dict[str, Any]:
        """
        Analyze how well recommendations performed in the given window. (Async)
        """
        recs = await self.tracker.get_recent_recommendations(window_days=window_days)
        if not recs:
            return {"status": "insufficient_data"}
            
        total = len(recs)
        # Assuming recommendation has 'status', 'confidence', and 'actual_outcome'
        # RecommendationStatus: ACCEPTED, REJECTED, IGNORED
        # actual_outcome: Dict with 'utility_score'
        
        accepted = [r for r in recs if r.status.value == "accepted"]
        adoption_rate = len(accepted) / total if total > 0 else 0
        
        # Accuracy: When accepted, how many had positive outcomes (>0.5 utility)
        successful = [r for r in accepted if (r.actual_outcome or {}).get('utility_score', 0) > 0.5]
        accuracy_when_followed = len(successful) / len(accepted) if accepted else 0
        
        # Confidence Calibration: 
        # Do 90% confidence items succeed 90% of the time?
        calibration_error = self._calculate_calibration_error(accepted)
        
        # Trust Score: Combined metric
        # adoption * accuracy weighted by confidence
        trust_score = (adoption_rate * 0.4) + (accuracy_when_followed * 0.6)
        
        return {
            "window_days": window_days,
            "total_recommendations": total,
            "adoption_rate": adoption_rate,
            "accuracy_when_followed": accuracy_when_followed,
            "calibration_error": calibration_error,
            "overall_trust_score": trust_score,
            "reliability_status": self._get_reliability_status(trust_score)
        }
        
    def _calculate_calibration_error(self, accepted_recs: List[Any]) -> float:
        """Mean Absolute Error between stated confidence and actual outcome success (0 or 1)"""
        if not accepted_recs:
            return 0.0
            
        errors = []
        for r in accepted_recs:
            success = 1.0 if (r.actual_outcome or {}).get('utility_score', 0) > 0.5 else 0.0
            errors.append(abs(r.confidence - success))
            
        return np.mean(errors)
        
    def _get_reliability_status(self, score: float) -> str:
        if score > 0.8: return "High (Verified)"
        if score > 0.6: return "Nominal (Adapting)"
        if score > 0.4: return "Caution (Learning)"
        return "Low (Calibration Required)"

    def generate_reliability_heatmap(self, recs: List[Any]) -> Dict[str, Any]:
        """
        Group accuracy by equipment type or zone to find 'blind spots'.
        """
        heatmap = {}
        for r in recs:
            if r.status.value != "accepted": continue
            
            # Simple grouping by equipment category
            key = r.recommended_action.get("target_id", "unknown").split("-")[0]
            if key not in heatmap:
                heatmap[key] = {"count": 0, "success": 0}
            
            heatmap[key]["count"] += 1
            if r.actual_outcome.get('utility_score', 0) > 0.5:
                heatmap[key]["success"] += 1
                
        # Calculate rates
        results = {}
        for k, v in heatmap.items():
            results[k] = v["success"] / v["count"] if v["count"] > 0 else 0
            
        return results
