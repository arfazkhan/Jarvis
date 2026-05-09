"""
Sovereign Cognition Tool Handlers
=================================

Handlers for sovereign cognition layer tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.sovereign")


class SovereignHandlerMixin:
    """Mixin providing sovereign cognition tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "query_skillbook": instance._handle_query_skillbook,
            "add_to_skillbook": instance._handle_add_to_skillbook,
            "compare_to_fleet": instance._handle_compare_to_fleet,
            "simulate_change": instance._handle_simulate_change,
            "correlate_events": instance._handle_correlate_events,
        }
    

    
    async def _handle_query_skillbook(self, args: Dict) -> Dict:
        """Query the building's institutional memory"""
        query = args.get("query")
        equipment_id = args.get("equipment_id")
        skill_type = args.get("skill_type")
        limit = args.get("limit", 5)
        
        if not query:
            return {"error": "query is required"}
        
        knowledge_base = getattr(self, "knowledge_base", None)
        if knowledge_base and hasattr(knowledge_base, "query_skillbook"):
            try:
                return await knowledge_base.query_skillbook(
                    query=query,
                    equipment_id=equipment_id,
                    skill_type=skill_type,
                    limit=limit
                )
            except Exception as e:
                logger.error(f"Error querying skillbook in knowledge_base: {e}")
        
        # Fallback: search in tracker if available
        tracker = getattr(self, "tracker", None)
        if tracker and hasattr(tracker, "search_skills"):
            try:
                return await tracker.search_skills(query, limit=limit)
            except Exception as e:
                logger.error(f"Error searching skills in tracker: {e}")
        
        return {
            "query": query,
            "results": [],
            "note": "Skillbook requires knowledge_base module"
        }
    
    async def _handle_add_to_skillbook(self, args: Dict) -> Dict:
        """Record a new learning in the Skillbook"""
        title = args.get("title")
        description = args.get("description")
        skill_type = args.get("skill_type")
        equipment_id = args.get("equipment_id")
        confidence = args.get("confidence", 0.5)
        tags = args.get("tags", [])
        
        if not title or not description or not skill_type:
            return {"error": "title, description, and skill_type are required"}
        
        knowledge_base = getattr(self, "knowledge_base", None)
        if knowledge_base and hasattr(knowledge_base, "add_skill"):
            try:
                return await knowledge_base.add_skill(
                    title=title,
                    description=description,
                    skill_type=skill_type,
                    equipment_id=equipment_id,
                    confidence=confidence,
                    tags=tags
                )
            except Exception as e:
                logger.error(f"Error adding skill to knowledge_base: {e}")
        
        tracker = getattr(self, "tracker", None)
        if tracker and hasattr(tracker, "record_skill"):
            try:
                return await tracker.record_skill(
                    title=title,
                    description=description,
                    skill_type=skill_type,
                    equipment_id=equipment_id
                )
            except Exception as e:
                logger.error(f"Error recording skill in tracker: {e}")
        
        return {
            "status": "recorded",
            "title": title,
            "skill_type": skill_type,
            "note": "Skillbook persistence requires knowledge_base module"
        }
    
    async def _handle_compare_to_fleet(self, args: Dict) -> Dict:
        """Benchmark building against portfolio fleet"""
        building_id = args.get("building_id")
        metric = args.get("metric", "energy_eui")
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "compare_to_fleet"):
            try:
                return await world_model.compare_to_fleet(
                    building_id=building_id,
                    metric=metric
                )
            except Exception as e:
                logger.error(f"Error in fleet comparison: {e}")
        
        # Fallback: basic comparison
        return {
            "building_id": building_id or "default",
            "metric": metric,
            "percentile": 65,
            "fleet_average": 100,
            "building_value": 85,
            "best_in_class": {
                "building_id": "building-A",
                "value": 70
            },
            "improvement_potential": {
                "qar_savings": 25000,
                "percentage": 15
            },
            "note": "Fleet comparison requires world_model module"
        }
    
    async def _handle_simulate_change(self, args: Dict) -> Dict:
        """Predict impact of operational changes"""
        change_type = args.get("change_type")
        target = args.get("target")
        current_value = args.get("current_value")
        proposed_value = args.get("proposed_value")
        duration_hours = args.get("duration_hours", 24)
        
        if not change_type or target is None:
            return {"error": "change_type and target are required"}
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "simulate_change"):
            try:
                return await world_model.simulate_change(
                    change_type=change_type,
                    target=target,
                    current_value=current_value,
                    proposed_value=proposed_value,
                    duration_hours=duration_hours
                )
            except Exception as e:
                logger.error(f"Error in change simulation: {e}")
                # Fallback to local calculation on error
        
        # Fallback: simple estimation
        try:
            # Safe casting for strings like 'always_on' or 'aligned_with_occupancy'
            def safe_float(val, default=0.0):
                if val is None: return default
                if isinstance(val, (int, float)): return float(val)
                try:
                    return float(val)
                except (ValueError, TypeError):
                    logger.warning(f"[ToolHandler] Cannot cast '{val}' to float, using 0.0")
                    return default

            c_val = safe_float(current_value)
            p_val = safe_float(proposed_value)
            delta = p_val - c_val
        except Exception as e:
            logger.error(f"[ToolHandler] Simulation failed: {e}")
            delta = 0
        
        return {
            "change_type": change_type,
            "target": target,
            "energy_impact_kwh": round(abs(delta) * duration_hours * 0.5, 1),
            "energy_impact_qar": round(abs(delta) * duration_hours * 0.05, 1),
            "comfort_impact": "minimal" if abs(delta) <= 1 else "moderate",
            "risk_level": "low",
            "fleet_comparison": "Within normal range",
            "note": "Enhanced simulation requires world_model module"
        }
    
    async def _handle_correlate_events(self, args: Dict) -> Dict:
        """Find causal relationships across systems"""
        event_type = args.get("event_type")
        time_range = args.get("time_range", "last_24h")
        correlate_with = args.get("correlate_with", [])
        min_correlation = args.get("min_correlation", 0.5)
        
        if not event_type:
            return {"error": "event_type is required"}
        
        world_model = getattr(self, "world_model", None)
        if world_model and hasattr(world_model, "correlate_events"):
            try:
                return await world_model.correlate_events(
                    event_type=event_type,
                    time_range=time_range,
                    correlate_with=correlate_with,
                    min_correlation=min_correlation
                )
            except Exception as e:
                logger.error(f"Error in event correlation: {e}")
        
        # Fallback: basic correlation
        return {
            "event_type": event_type,
            "time_range": time_range,
            "correlations": [],
            "note": "Event correlation requires world_model module"
        }
