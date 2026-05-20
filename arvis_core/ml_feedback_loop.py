"""
ML Feedback Loop
================

Records prediction outcomes and operator feedback.
Feeds accuracy data back into RetrainScheduler for continual learning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.ml_feedback_loop")


class MLFeedbackLoop:
    """
    Closes the continual learning loop:
    - Prediction outcomes (actual vs predicted) → model accuracy tracking
    - Operator feedback (accept/reject) → preference model retraining
    - Failed predictions → RetrainScheduler investigation trigger
    """

    def __init__(self):
        self._outcomes: List[Dict[str, Any]] = []
        self._feedback: List[Dict[str, Any]] = []

    async def record_prediction_outcome(
        self,
        evidence_id: str,
        model_id: str,
        predicted: Any,
        actual: Any,
        metric_name: str = "error",
    ) -> None:
        """Record what actually happened vs what was predicted."""
        try:
            error = abs(float(actual) - float(predicted)) / max(abs(float(actual)), 1e-9)
        except (TypeError, ValueError):
            error = None

        record = {
            "evidence_id": evidence_id,
            "model_id": model_id,
            "predicted": predicted,
            "actual": actual,
            "error": error,
            "metric_name": metric_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._outcomes.append(record)

        if error is not None:
            try:
                from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
                get_retrain_scheduler().record_performance(
                    model_name=model_id,
                    metric_value=error,
                )
                logger.debug(f"[FeedbackLoop] {model_id} error={error:.3f} recorded in scheduler")
            except Exception as e:
                logger.debug(f"[FeedbackLoop] scheduler feed failed: {e}")

        # Trigger investigation if error is very high
        if error is not None and error > 0.5:
            logger.warning(f"[FeedbackLoop] High prediction error for {model_id}: {error:.2f}. Flagging for retrain.")
            try:
                from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
                sched = get_retrain_scheduler()
                sched.record_performance(model_name=model_id, metric_value=error)
                sched.record_performance(model_name=model_id, metric_value=error)  # double-count to push over threshold
            except Exception:
                pass

    async def record_operator_feedback(
        self,
        evidence_id: str,
        advisory_text: str,
        accepted: bool,
        rating: float = 0.5,
        notes: str = "",
    ) -> None:
        """Record operator accept/reject decision on an advisory."""
        record = {
            "evidence_id": evidence_id,
            "accepted": accepted,
            "rating": max(0.0, min(1.0, rating)),
            "notes": notes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._feedback.append(record)
        logger.info(f"[FeedbackLoop] Operator feedback: evidence={evidence_id} accepted={accepted} rating={rating:.2f}")

        # Feed into OutcomePredictor training buffer
        try:
            from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
            predictor = OutcomePredictor()
            predictor.load()
            if hasattr(predictor, "record_feedback"):
                predictor.record_feedback(
                    advisory_text=advisory_text,
                    accepted=accepted,
                    rating=rating,
                )
        except Exception as e:
            logger.debug(f"[FeedbackLoop] OutcomePredictor feedback failed: {e}")

        # Feed into PreferenceRankingModel
        try:
            from agent_advisory.ml_models.preference_ranker import PreferenceRankingModel
            ranker = PreferenceRankingModel()
            ranker.load()
            if hasattr(ranker, "record_feedback"):
                ranker.record_feedback(
                    advisory_text=advisory_text,
                    accepted=accepted,
                    rating=rating,
                )
        except Exception as e:
            logger.debug(f"[FeedbackLoop] PreferenceRanker feedback failed: {e}")

    async def compute_model_accuracy(
        self,
        model_id: str,
        window_hours: int = 168,
    ) -> Dict[str, Any]:
        """Compute accuracy metrics for a model over the given window."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        relevant = [
            r for r in self._outcomes
            if r["model_id"] == model_id
            and datetime.fromisoformat(r["timestamp"]) >= cutoff
            and r.get("error") is not None
        ]
        if not relevant:
            return {"model_id": model_id, "window_hours": window_hours, "n_samples": 0, "status": "no_data"}

        errors = [r["error"] for r in relevant]
        import statistics
        return {
            "model_id": model_id,
            "window_hours": window_hours,
            "n_samples": len(errors),
            "mean_error": round(statistics.mean(errors), 4),
            "max_error": round(max(errors), 4),
            "median_error": round(statistics.median(errors), 4),
            "needs_retrain": statistics.mean(errors) > 0.15,
        }

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_outcomes": len(self._outcomes),
            "total_feedback": len(self._feedback),
            "accepted_count": sum(1 for f in self._feedback if f.get("accepted")),
            "rejected_count": sum(1 for f in self._feedback if not f.get("accepted")),
        }


_feedback_loop_instance: Optional[MLFeedbackLoop] = None


def get_feedback_loop() -> MLFeedbackLoop:
    global _feedback_loop_instance
    if _feedback_loop_instance is None:
        _feedback_loop_instance = MLFeedbackLoop()
    return _feedback_loop_instance
