"""
Recommendation Tracker
======================

Tracks all advisory recommendations and operator responses.

This is the foundation for trust calibration and preference learning.
Every recommendation ARVIS makes is logged here with:
- What was recommended
- What the operator chose to do
- What actually happened (outcome)
"""

import uuid
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from agent_advisory.database import AdvisoryDatabase
from agent_advisory.schemas import (
    Recommendation,
    RecommendationStatus,
    OutcomeQuality,
    TrustMetrics
)

logger = logging.getLogger("arvis.advisory.tracker")


class RecommendationTracker:
    """
    Tracks recommendations and operator responses.
    
    Usage:
        tracker = RecommendationTracker()
        
        # When ARVIS makes a recommendation
        rec_id = tracker.log_recommendation(
            context={"alarm": "high_head_pressure", ...},
            recommended_action={"action": "shutdown", ...},
            confidence=0.85,
            reasoning="High risk of compressor damage",
            predicted_outcome={"energy_savings_kwh": 0, ...}
        )
        
        # When operator makes a decision
        tracker.log_operator_decision(
            recommendation_id=rec_id,
            operator_choice={"action": "reduce_load", ...},
            operator_id="john_doe"
        )
        
        # When outcome is known (e.g., from verification engine)
        tracker.log_outcome(
            recommendation_id=rec_id,
            actual_outcome={"energy_savings_kwh": -150, ...},
            outcome_quality=OutcomeQuality.GOOD
        )
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize tracker with database"""
        self.db = AdvisoryDatabase(db_path)
        logger.info("Recommendation tracker initialized")
    
    def log_recommendation(
        self,
        context: Dict[str, Any],
        recommended_action: Dict[str, Any],
        confidence: float,
        reasoning: str = "",
        predicted_outcome: Optional[Dict[str, Any]] = None,
        trigger_type: str = "alarm",
        building_id: str = "unknown",
        equipment_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        calibrated_confidence: Optional[float] = None
    ) -> str:
        """
        Log a new recommendation.
        
        Returns:
            recommendation_id: UUID of the logged recommendation
        """
        
        rec = Recommendation(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            context=context,
            trigger_type=trigger_type,
            recommended_action=recommended_action,
            confidence=confidence,
            calibrated_confidence=calibrated_confidence or confidence,
            reasoning=reasoning,
            predicted_outcome=predicted_outcome,
            building_id=building_id,
            equipment_ids=equipment_ids or [],
            tags=tags or []
        )
        
        # Store in database
        data = rec.to_dict()
        self.db.execute(
            """
            INSERT INTO recommendations (
                id, timestamp, context, trigger_type,
                recommended_action, confidence, calibrated_confidence,
                reasoning, predicted_outcome, status, human_action,
                decision_time, operator_id, actual_outcome,
                outcome_quality, outcome_measured_at, building_id,
                equipment_ids, tags
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?
            )
            """,
            tuple(data.values())
        )
        
        logger.info(f"Logged recommendation {rec.id}: {recommended_action.get('action', 'unknown')}")
        return rec.id
    
    def log_operator_decision(
        self,
        recommendation_id: str,
        operator_choice: Dict[str, Any],
        operator_id: str = "unknown"
    ):
        """
        Log what the operator actually chose to do.
        
        This is called when the operator executes an action,
        either following the recommendation or choosing something else.
        """
        
        # Get current recommendation
        rec_data = self.db.fetch_one(
            "SELECT * FROM recommendations WHERE id = ?",
            (recommendation_id,)
        )
        
        if not rec_data:
            logger.warning(f"Recommendation {recommendation_id} not found")
            return
        
        rec = Recommendation.from_dict(rec_data)
        
        # Determine status
        if self._actions_match(rec.recommended_action, operator_choice):
            status = RecommendationStatus.ACCEPTED
        elif self._actions_similar(rec.recommended_action, operator_choice):
            status = RecommendationStatus.MODIFIED
        else:
            status = RecommendationStatus.REJECTED
        
        # Update database
        import json
        self.db.execute(
            """
            UPDATE recommendations
            SET human_action = ?, status = ?, 
                decision_time = ?, operator_id = ?
            WHERE id = ?
            """,
            (json.dumps(operator_choice), status.value,
             time.time(), operator_id, recommendation_id)
        )
        
        logger.info(
            f"Operator decision logged for {recommendation_id}: "
            f"{status.value} ({operator_id})"
        )
    
    def log_outcome(
        self,
        recommendation_id: str,
        actual_outcome: Dict[str, Any],
        outcome_quality: OutcomeQuality = OutcomeQuality.UNKNOWN
    ):
        """
        Log the actual outcome of the recommendation.
        
        This is typically called by the verification engine
        after some time has passed.
        """
        
        import json
        self.db.execute(
            """
            UPDATE recommendations
            SET actual_outcome = ?, outcome_quality = ?, 
                outcome_measured_at = ?
            WHERE id = ?
            """,
            (json.dumps(actual_outcome), outcome_quality.value,
             time.time(), recommendation_id)
        )
        
        logger.info(
            f"Outcome logged for {recommendation_id}: "
            f"{outcome_quality.value}"
        )
    
    def get_recommendation(self, recommendation_id: str) -> Optional[Recommendation]:
        """Get a single recommendation by ID"""
        data = self.db.fetch_one(
            "SELECT * FROM recommendations WHERE id = ?",
            (recommendation_id,)
        )
        return Recommendation.from_dict(data) if data else None
    
    def get_recent_recommendations(
        self,
        window_days: int = 30,
        building_id: Optional[str] = None,
        operator_id: Optional[str] = None
    ) -> List[Recommendation]:
        """Get recent recommendations within time window"""
        
        cutoff = time.time() - (window_days * 24 * 60 * 60)
        
        query = "SELECT * FROM recommendations WHERE timestamp >= ?"
        params = [cutoff]
        
        if building_id:
            query += " AND building_id = ?"
            params.append(building_id)
        
        if operator_id:
            query += " AND operator_id = ?"
            params.append(operator_id)
        
        query += " ORDER BY timestamp DESC"
        
        rows = self.db.fetch_all(query, tuple(params))
        return [Recommendation.from_dict(row) for row in rows]
    
    def calculate_trust_metrics(
        self,
        window_days: int = 30,
        building_id: Optional[str] = None
    ) -> TrustMetrics:
        """
        Calculate trust metrics for a time period.
        
        Returns:
            TrustMetrics object with adoption rate, accuracy, calibration, etc.
        """
        
        recs = self.get_recent_recommendations(window_days, building_id)
        
        if not recs:
            # No data
            return TrustMetrics(
                date=datetime.now().date().isoformat(),
                total_recommendations=0,
                adoption_rate=0.0,
                acceptance_count=0,
                rejection_count=0,
                modification_count=0,
                accuracy_when_followed=0.0,
                excellent_outcomes=0,
                good_outcomes=0,
                acceptable_outcomes=0,
                poor_outcomes=0,
                calibration_error=0.0
            )
        
        # Calculate adoption metrics
        total = len(recs)
        accepted = sum(1 for r in recs if r.status == RecommendationStatus.ACCEPTED)
        rejected = sum(1 for r in recs if r.status == RecommendationStatus.REJECTED)
        modified = sum(1 for r in recs if r.status == RecommendationStatus.MODIFIED)
        
        adoption_rate = (accepted + modified * 0.5) / total if total > 0 else 0.0
        
        # Calculate accuracy when followed
        followed = [r for r in recs if r.status == RecommendationStatus.ACCEPTED]
        with_outcomes = [r for r in followed if r.outcome_quality != OutcomeQuality.UNKNOWN]
        
        if with_outcomes:
            excellent = sum(1 for r in with_outcomes if r.outcome_quality == OutcomeQuality.EXCELLENT)
            good = sum(1 for r in with_outcomes if r.outcome_quality == OutcomeQuality.GOOD)
            acceptable = sum(1 for r in with_outcomes if r.outcome_quality == OutcomeQuality.ACCEPTABLE)
            poor = sum(1 for r in with_outcomes if r.outcome_quality == OutcomeQuality.POOR)
            
            # Accuracy = (excellent + good) / total
            accuracy = (excellent + good) / len(with_outcomes)
        else:
            excellent = good = acceptable = poor = 0
            accuracy = 0.0
        
        # Calculate calibration error
        calibration_error, calibration_buckets = self._compute_calibration(recs)
        
        metrics = TrustMetrics(
            date=datetime.now().date().isoformat(),
            total_recommendations=total,
            adoption_rate=adoption_rate,
            acceptance_count=accepted,
            rejection_count=rejected,
            modification_count=modified,
            accuracy_when_followed=accuracy,
            excellent_outcomes=excellent,
            good_outcomes=good,
            acceptable_outcomes=acceptable,
            poor_outcomes=poor,
            calibration_error=calibration_error,
            calibration_buckets=calibration_buckets
        )
        
        # Store in database
        import json
        data = metrics.to_dict()
        self.db.execute(
            """
            INSERT OR REPLACE INTO trust_metrics (
                date, total_recommendations, adoption_rate,
                acceptance_count, rejection_count, modification_count,
                accuracy_when_followed, excellent_outcomes, good_outcomes,
                acceptable_outcomes, poor_outcomes, calibration_error,
                calibration_buckets, regret_rate, false_alarm_rate
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            tuple(data.values())
        )
        
        logger.info(
            f"Trust metrics calculated: "
            f"adoption={adoption_rate:.1%}, accuracy={accuracy:.1%}, "
            f"calibration_error={calibration_error:.2f}"
        )
        
        return metrics
    
    def _compute_calibration(self, recs: List[Recommendation]):
        """
        Compute calibration error.
        
        For each confidence bucket (0.0, 0.1, ..., 1.0),
        check if stated confidence matches actual accuracy.
        """
        from collections import defaultdict
        
        # Group by confidence buckets
        buckets = defaultdict(list)
        for rec in recs:
            if rec.outcome_quality != OutcomeQuality.UNKNOWN:
                bucket = round(rec.calibrated_confidence or rec.confidence, 1)
                was_good = rec.outcome_quality in [OutcomeQuality.EXCELLENT, OutcomeQuality.GOOD]
                buckets[bucket].append(was_good)
        
        # Compute calibration per bucket
        calibration_buckets = {}
        errors = []
        
        for bucket, outcomes in buckets.items():
            actual_accuracy = sum(outcomes) / len(outcomes) if outcomes else 0.0
            error = abs(bucket - actual_accuracy)
            errors.append(error)
            
            calibration_buckets[str(bucket)] = {
                "stated": bucket,
                "actual": actual_accuracy,
                "count": len(outcomes),
                "error": error
            }
        
        # Overall calibration error = mean absolute error
        calibration_error = sum(errors) / len(errors) if errors else 0.0
        
        return calibration_error, calibration_buckets
    
    def _actions_match(self, action1: Dict, action2: Dict) -> bool:
        """Check if two actions are the same"""
        # Simple comparison - can be made more sophisticated
        return action1.get("action") == action2.get("action")
    
    def _actions_similar(self, action1: Dict, action2: Dict) -> bool:
        """Check if two actions are similar (modified version)"""
        # Example: "shutdown" vs "reduce_load_then_shutdown"
        action1_type = action1.get("action", "")
        action2_type = action2.get("action", "")
        
        # Same action type
        if action1_type == action2_type:
            return True
        
        # Related actions
        similar_pairs = [
            ("shutdown", "reduce_load"),
            ("increase_setpoint", "decrease_setpoint"),
        ]
        
        for pair in similar_pairs:
            if (action1_type in pair and action2_type in pair):
                return True
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics"""
        return self.db.get_stats()
