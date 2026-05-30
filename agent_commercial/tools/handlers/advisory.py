"""
Advisory Tool Handlers
======================

Handlers for proactive advisory, briefings, and feedback tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.advisory")


class AdvisoryHandlerMixin:
    """Mixin providing advisory-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "get_advisory_recommendations": instance._handle_get_advisory_recommendations,
            "check_goals": instance._handle_check_goals,
            "generate_briefing": instance._handle_generate_briefing,
            "run_briefing": instance._handle_run_briefing,
            "submit_feedback": instance._handle_submit_feedback,
            "get_trust_metrics": instance._handle_get_trust_metrics,
        }
    
    async def _handle_get_advisory_recommendations(self, args: Dict) -> Dict:
        """Get AI-generated recommendations for operational issues"""
        context = args.get("context", "")
        equipment_id = args.get("equipment_id")
        alarm_id = args.get("alarm_id")
        top_k = args.get("top_k", 3)
        
        advisor = getattr(self, "advisor", None)
        if advisor and hasattr(advisor, "get_recommendations"):
            try:
                return await advisor.get_recommendations(
                    context=context,
                    equipment_id=equipment_id,
                    alarm_id=alarm_id,
                    top_k=top_k
                )
            except Exception as e:
                logger.error(f"Error getting recommendations from advisor: {e}")
        
        # Fallback recommendations
        return {
            "context": context,
            "recommendations": [
                {
                    "id": "rec-001",
                    "title": "Monitor Current Conditions",
                    "description": "Continue monitoring and gather more data",
                    "confidence": 0.7,
                    "impact": "low",
                    "risk": "low"
                }
            ],
            "note": "Enhanced recommendations require advisor module"
        }
    
    async def _handle_check_goals(self, args: Dict) -> Dict:
        """Check for active proactive goals.

        Returns canonical schema: goals, total, highest_priority_category.
        Back-fills defaults on any failure (B11 schema fix).
        """
        category = args.get("category")
        default_response = {
            "goals": [],
            "total": 0,
            "highest_priority_category": "",
        }

        goal_generator = getattr(self, "goal_generator", None)
        if goal_generator and hasattr(goal_generator, "get_active_goals"):
            try:
                goals = goal_generator.get_active_goals(category=category) or []
                top_cat = ""
                if goals:
                    cats = [g.get("category", "") for g in goals if g.get("priority", 99) <= 1]
                    top_cat = cats[0] if cats else goals[0].get("category", "operational")
                return {
                    "goals": goals,
                    "total": len(goals),
                    "highest_priority_category": top_cat,
                }
            except Exception as e:
                logger.error(f"Error getting active goals: {e}")

        return default_response

    async def _handle_generate_briefing(self, args: Dict) -> Dict:
        """Generate a proactive operations briefing.

        Returns canonical schema: briefing_type, critical_items, anomalies,
        optimization_wins, context, recommendations, generated_at. Back-fills
        any missing keys from briefing_scheduler response (B11 schema fix).
        """
        briefing_type = args.get("briefing_type", "daily_morning")
        focus_area = args.get("focus_area")

        # Canonical default — keeps all schema keys present
        default_response = {
            "briefing_type": briefing_type,
            "generated_at": __import__('datetime').datetime.now().isoformat(),
            "critical_items": [],
            "anomalies": [],
            "optimization_wins": [],
            "context": {
                "weather": "Clear, 35°C",
                "events": [],
                "tariff_period": "peak",
            },
            "recommendations": [],
        }

        briefing_scheduler = getattr(self, "briefing_scheduler", None)
        if briefing_scheduler and hasattr(briefing_scheduler, "generate_briefing"):
            try:
                result = await briefing_scheduler.generate_briefing(
                    briefing_type=briefing_type,
                    focus_area=focus_area
                )
                if isinstance(result, dict):
                    # B11: back-fill any missing schema keys from scheduler response
                    for key, fallback in default_response.items():
                        result.setdefault(key, fallback)
                    return result
            except Exception as e:
                logger.error(f"Error generating briefing: {e}")

        return default_response
    
    async def _handle_run_briefing(self, args: Dict) -> Dict:
        """Run an on-demand briefing (alias for generate_briefing)"""
        return await self._handle_generate_briefing(args)
    
    async def _handle_submit_feedback(self, args: Dict) -> Dict:
        """Submit operator feedback for active learning"""
        feedback_type = args.get("feedback_type")
        target = args.get("target")
        content = args.get("content")
        rating = args.get("rating")
        
        from datetime import datetime as _dt
        import uuid as _uuid

        def _normalize(res: dict, model_updated: bool) -> dict:
            # Schema keys: accepted, feedback_id, model_updated, timestamp
            res.setdefault("accepted", "error" not in res)
            res.setdefault("feedback_id", res.get("id") or str(_uuid.uuid4()))
            res.setdefault("model_updated", model_updated)
            res.setdefault("timestamp", _dt.now().isoformat())
            return res

        feedback_loop = getattr(self, "feedback_loop", None)
        if feedback_loop and hasattr(feedback_loop, "submit_feedback"):
            try:
                res = await feedback_loop.submit_feedback(
                    feedback_type=feedback_type,
                    target=target,
                    content=content,
                    rating=rating
                )
                if isinstance(res, dict):
                    return _normalize(res, model_updated=True)
            except Exception as e:
                logger.error(f"Error submitting feedback to loop: {e}")

        tracker = getattr(self, "tracker", None)
        if tracker and hasattr(tracker, "record_feedback"):
            try:
                tracker.record_feedback(target, feedback_type, content)
            except Exception as e:
                logger.error(f"Error recording feedback in tracker: {e}")

        return _normalize({
            "status": "recorded",
            "feedback_type": feedback_type,
            "target": target,
        }, model_updated=False)
    
    async def _handle_get_trust_metrics(self, args: Dict) -> Dict:
        """Get trust and drift metrics for the advisor"""
        window_days = args.get("window_days", 30)
        
        trust_data = {}
        drift_data = {}
        
        trust_calibrator = getattr(self, "trust_calibrator", None)
        if trust_calibrator and hasattr(trust_calibrator, "calculate_trust_metrics"):
            try:
                trust_data = await trust_calibrator.calculate_trust_metrics(window_days)
            except Exception as e:
                logger.error(f"Error calculating trust metrics: {e}")
            
        online_learner = getattr(self, "online_learner", None)
        if online_learner and hasattr(online_learner, "get_performance_summary"):
            try:
                drift_data = online_learner.get_performance_summary()
            except Exception as e:
                logger.error(f"Error getting performance summary: {e}")
            
        from datetime import datetime as _dt
        td = trust_data if isinstance(trust_data, dict) else {}
        dd = drift_data if isinstance(drift_data, dict) else {}
        drift_detected = dd.get("drift_ratio", 1) >= 1.3 or bool(dd.get("drift_detected"))
        return {
            "trust_metrics": td,
            "performance_drift": dd,
            "system_status": "Healthy" if not drift_detected else "Performance Degraded",
            # Schema keys — surface nested values, never null
            "overall_trust_score": td.get("overall_trust_score") or td.get("trust_score") or 0.0,
            "recommendation_adoption_rate": td.get("recommendation_adoption_rate") or td.get("adoption_rate") or 0.0,
            "prediction_accuracy": td.get("prediction_accuracy") or dd.get("accuracy") or 0.0,
            "model_drift_detected": drift_detected,
            "feedback_count": td.get("feedback_count") or td.get("sample_count") or 0,
            "last_updated": td.get("last_updated") or _dt.now().isoformat(),
        }
