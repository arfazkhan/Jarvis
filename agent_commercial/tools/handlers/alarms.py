"""
Alarm Tool Handlers
===================

Handlers for alarm-related BMS tools.
"""

import logging
from typing import Dict, Any

from agent_advisory.explainer import DetailLevel

logger = logging.getLogger("arvis.bms.tools.alarms")


class AlarmHandlerMixin:
    """Mixin providing alarm-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "get_active_alarms": instance._handle_get_active_alarms,
            "explain_alarm": instance._handle_explain_alarm,
            "acknowledge_alarm": instance._handle_acknowledge_alarm,
            "analyze_cascade": instance._handle_analyze_cascade,
        }
    
    async def _handle_get_active_alarms(self, args: Dict) -> Dict:
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        queue = self.alarm_engine.get_priority_queue()
        
        severity = args.get("severity")
        equipment_id = args.get("equipment_id")
        limit = args.get("limit", 20)
        
        if severity:
            queue = [a for a in queue if a.alarm.severity.value == severity]
        if equipment_id:
            queue = [a for a in queue if a.alarm.equipment_id == equipment_id]
        
        return {
            "count": len(queue[:limit]),
            "alarms": [a.to_dict() for a in queue[:limit]]
        }
    
    async def _handle_explain_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        report = self.alarm_engine.get_root_cause_analysis(alarm_id)
        result = report.to_dict()
        
        # Phase 5: Enhance with high-fidelity explanation if available
        if self.explainer and result.get("recommendation"):
            # Get current context from BMS State
            context = {"total_power_kw": 400, "zone_temp_avg_c": 23.5}  # Fallback
            if self.bms_state:
                try:
                    points = await self.bms_state.get_points_by_equipment(result.get("root_cause_id", ""))
                    context = {p.point_id.split("/")[-1].lower(): p.value for p in points}
                except Exception:
                    pass
                
            explanation = await self.explainer.explain_recommendation(
                recommendation={"title": "Alarm Resolution", "description": result["recommendation"]},
                context=context,
                level=DetailLevel.STANDARD
            )
            result["high_fidelity_explanation"] = explanation["text"]
            result["causal_chain"] = explanation["causal_chain"]
            
        return result
    
    async def _handle_acknowledge_alarm(self, args: Dict) -> Dict:
        alarm_id = args.get("alarm_id")
        
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        success = await self.bms_state.acknowledge_alarm(alarm_id, "ops_copilot")
        return {"success": success, "alarm_id": alarm_id}
    
    async def _handle_analyze_cascade(self, args: Dict) -> Dict:
        """Analyze alarm cascade to find root cause"""
        alarm_ids = args.get("alarm_ids", [])
        time_window = args.get("time_window_minutes", 30)
        
        if not self.alarm_engine:
            return {"error": "Alarm engine not configured"}
        
        # Get cascade analysis from alarm engine
        if hasattr(self.alarm_engine, "analyze_cascade"):
            return await self.alarm_engine.analyze_cascade(alarm_ids, time_window)
        
        # Fallback: basic cascade detection
        return {
            "alarm_ids": alarm_ids,
            "root_cause_alarm": alarm_ids[0] if alarm_ids else None,
            "cascade_tree": [],
            "analysis_note": "Cascade analysis requires enhanced alarm engine"
        }
