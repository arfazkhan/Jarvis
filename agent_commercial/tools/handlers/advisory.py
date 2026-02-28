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
        
        if self.advisor:
            return await self.advisor.get_recommendations(
                context=context,
                equipment_id=equipment_id,
                alarm_id=alarm_id,
                top_k=top_k
            )
        
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
        
        if self.goal_generator:
            goals = self.goal_generator.get_active_goals(category=category)
            return {
                "goals": goals,
                "count": len(goals)
            }
        
        return {
            "goals": [],
            "note": "Goal generator not configured"
        }
    
    async def _handle_generate_briefing(self, args: Dict) -> Dict:
        """Generate a proactive operations briefing"""
        briefing_type = args.get("briefing_type", "daily_morning")
        focus_area = args.get("focus_area")
        
        if self.briefing_scheduler:
            return await self.briefing_scheduler.generate_briefing(
                briefing_type=briefing_type,
                focus_area=focus_area
            )
        
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
        
        if self.feedback_loop:
            return await self.feedback_loop.submit_feedback(
                feedback_type=feedback_type,
                target=target,
                content=content,
                rating=rating
            )
        
        if self.tracker:
            self.tracker.record_feedback(target, feedback_type, content)
        
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
        
        if self.trust_calibrator:
            trust_data = await self.trust_calibrator.calculate_trust_metrics(window_days)
            
        if self.online_learner:
            drift_data = self.online_learner.get_performance_summary()
            
        return {
            "trust_metrics": trust_data,
            "performance_drift": drift_data,
            "system_status": "Healthy" if drift_data.get("drift_ratio", 1) < 1.3 else "Performance Degraded"
        }
