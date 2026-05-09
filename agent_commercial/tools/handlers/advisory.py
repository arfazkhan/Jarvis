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
        """Check for active proactive goals"""
        category = args.get("category")
        
        goal_generator = getattr(self, "goal_generator", None)
        if goal_generator and hasattr(goal_generator, "get_active_goals"):
            try:
                goals = goal_generator.get_active_goals(category=category)
                return {
                    "goals": goals,
                    "count": len(goals)
                }
            except Exception as e:
                logger.error(f"Error getting active goals: {e}")
        
        return {
            "goals": [],
            "note": "Goal generator not configured"
        }
    
    async def _handle_generate_briefing(self, args: Dict) -> Dict:
        """Generate a proactive operations briefing"""
        briefing_type = args.get("briefing_type", "daily_morning")
        focus_area = args.get("focus_area")
        
        briefing_scheduler = getattr(self, "briefing_scheduler", None)
        if briefing_scheduler and hasattr(briefing_scheduler, "generate_briefing"):
            try:
                return await briefing_scheduler.generate_briefing(
                    briefing_type=briefing_type,
                    focus_area=focus_area
                )
            except Exception as e:
                logger.error(f"Error generating briefing: {e}")
        
        # Fallback briefing
        return {
            "briefing_type": briefing_type,
            "generated_at": __import__('datetime').datetime.now().isoformat(),
            "sections": {
                "critical_items": [],
                "overnight_anomalies": [],
                "optimization_wins": [],
                "today_context": {
                    "weather": "Clear, 35°C",
                    "events": [],
                    "tariff_period": "peak"
                },
                "recommendations": []
            },
            "note": "Enhanced briefings require briefing_scheduler module"
        }
    
    async def _handle_run_briefing(self, args: Dict) -> Dict:
        """Run an on-demand briefing (alias for generate_briefing)"""
        return await self._handle_generate_briefing(args)
    
    async def _handle_submit_feedback(self, args: Dict) -> Dict:
        """Submit operator feedback for active learning"""
        feedback_type = args.get("feedback_type")
        target = args.get("target")
        content = args.get("content")
        rating = args.get("rating")
        
        feedback_loop = getattr(self, "feedback_loop", None)
        if feedback_loop and hasattr(feedback_loop, "submit_feedback"):
            try:
                return await feedback_loop.submit_feedback(
                    feedback_type=feedback_type,
                    target=target,
                    content=content,
                    rating=rating
                )
            except Exception as e:
                logger.error(f"Error submitting feedback to loop: {e}")
        
        tracker = getattr(self, "tracker", None)
        if tracker and hasattr(tracker, "record_feedback"):
            try:
                tracker.record_feedback(target, feedback_type, content)
            except Exception as e:
                logger.error(f"Error recording feedback in tracker: {e}")
        
        return {
            "status": "recorded",
            "feedback_type": feedback_type,
            "target": target
        }
    
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
            
        return {
            "trust_metrics": trust_data,
            "performance_drift": drift_data,
            "system_status": "Healthy" if drift_data.get("drift_ratio", 1) < 1.3 else "Performance Degraded"
        }
