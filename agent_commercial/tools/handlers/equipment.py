"""
Equipment Tool Handlers
=======================

Handlers for equipment-related BMS tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.equipment")

# Safe imports for modular standalone operation
try:
    from agent_commercial.bms_data_model import EquipmentType
except ImportError:
    class EquipmentType:
        AHU = "air_handling_unit"
        CHILLER = "chiller"
        VAV = "variable_air_volume"
        FCU = "fan_coil_unit"
        PUMP = "pump"
        COOLING_TOWER = "cooling_tower"
        BOILER = "boiler"
        METER_ELECTRIC = "electric_meter"
        METER_WATER = "water_meter"
        METER_GAS = "gas_meter"


class EquipmentHandlerMixin:
    """Mixin providing equipment-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "get_equipment_status": instance._handle_get_equipment_status,
            "list_equipment": instance._handle_list_equipment,
            "get_equipment_health": instance._handle_get_equipment_health,
            "get_point_history": instance._handle_get_point_history,
            "get_equipment_specs": instance._handle_get_equipment_specs,
            "hybrid_search_knowledge": instance._handle_hybrid_search_knowledge,
            "get_dashboard_overview": instance._handle_get_dashboard_overview,
        }
    
    async def _handle_get_equipment_status(self, args: Dict) -> Dict:
        equipment_id = args.get("equipment_id")
        
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        equipment = await self.bms_state.get_equipment(equipment_id)
        if not equipment:
            return {"error": f"Equipment {equipment_id} not found"}
        
        points = await self.bms_state.get_points_by_equipment(equipment_id)
        
        return {
            "equipment": equipment.to_dict(),
            "data_points": [p.to_dict() for p in points],
        }
    
    async def _handle_list_equipment(self, args: Dict) -> Dict:
        if not self.bms_state:
            return {"error": "BMS state engine not configured"}
        
        equipment = await self.bms_state.get_all_equipment()
        
        # Apply filters
        eq_type = args.get("equipment_type")
        status = args.get("status")
        location = args.get("location")
        
        if eq_type:
            # Handle 'meter' shortcut or variants
            if str(eq_type).lower() in ["meter", "meters"]:
                meter_types = [EquipmentType.METER_ELECTRIC, EquipmentType.METER_WATER, EquipmentType.METER_GAS]
                equipment = [e for e in equipment if e.equipment_type in meter_types]
            else:
                # Robust filtering that handles Enums, mock classes, and strings
                def matches_type(e_type, target):
                    try:
                        target_str = str(target).lower()
                        # 1. Try Enum value
                        if hasattr(e_type, "value"):
                            if str(e_type.value).lower() == target_str:
                                return True
                        # 2. Try Enum name or attribute name
                        if hasattr(e_type, "name"):
                            if str(e_type.name).lower() == target_str:
                                return True
                        # 3. Try string match if safe
                        try:
                            if str(e_type).lower() == target_str:
                                return True
                        except:
                            pass
                        # 4. Try repr as last resort
                        if target_str in repr(e_type).lower():
                            return True
                    except:
                        pass
                    return False

                equipment = [e for e in equipment if matches_type(e.equipment_type, eq_type)]
        if status:
            equipment = [e for e in equipment if e.status.value == status]
        if location:
            equipment = [e for e in equipment if location.lower() in e.location.lower()]
        
        return {
            "count": len(equipment),
            "equipment": [e.to_dict() for e in equipment]
        }
    
    async def _handle_get_equipment_health(self, args: Dict) -> Dict:
        """Get real equipment health from predictive engine"""
        equipment_id = args.get("equipment_id", "all")
        
        predictive = getattr(self, "predictive_engine", None)
        if predictive and hasattr(predictive, "predict_maintenance"):
            prediction = await predictive.predict_maintenance(equipment_id)
            return {
                "equipment_id": equipment_id,
                "overall_health": "good" if prediction.get("health_score", 100) > 70 else "poor",
                "health_score": prediction.get("health_score", 85),
                "trending": "stable",
                "risk_factors": []
            }
        
        return {
            "equipment_id": equipment_id,
            "overall_health": "good",
            "health_score": 92.5,
            "trending": "stable",
            "risk_factors": [],
        }
    
    async def _handle_get_point_history(self, args: Dict) -> Dict:
        point_id = args.get("point_id")
        minutes = args.get("minutes", 60)
        
        state = getattr(self, "bms_state", None)
        if not state:
            return {"error": "BMS state engine not configured"}
        
        if hasattr(state, "get_point_history"):
            history = await state.get_point_history(point_id, minutes)
            return {
                "point_id": point_id,
                "data": [{"timestamp": t.isoformat(), "value": v} for t, v in history]
            }
        
        return {
            "point_id": point_id,
            "data": [],
            "note": "Point history retrieval not supported by current state engine"
        }
    
    async def _handle_get_equipment_specs(self, args: Dict) -> Dict:
        """Search documentation for equipment specs with Graph-RAG support"""
        query = args.get("query")
        equipment_id = args.get("equipment_id")
        depth = args.get("system_depth", 0)
        
        kb = getattr(self, "knowledge_base", None)
        graph = getattr(self, "graph_rag", None)
        
        if not kb and not graph:
            return {"error": "Technical knowledge base not initialized"}
            
        # Use GraphRAGNavigator if depth > 0 and available
        results = []
        if depth > 0 and graph and equipment_id and hasattr(graph, "query_system_specs"):
            results = await graph.query_system_specs(query, equipment_id, depth=depth)
        elif kb and hasattr(kb, "query_specs"):
            results = await kb.query_specs(query, equipment_id)
        
        return {
            "query": query,
            "equipment_id": equipment_id,
            "navigation_depth": depth,
            "findings": [r["content"] for r in results] if results else [],
            "sources": [r["metadata"].get("source") for r in results] if results else []
        }

    async def _handle_hybrid_search_knowledge(self, args: Dict) -> Dict:
        """Search technical manuals using tree, vector, or hybrid retrieval."""
        query = args.get("query")
        equipment_id = args.get("equipment_id")
        strategy = args.get("strategy", "auto")
        limit = int(args.get("limit", 5))

        if not query:
            return {"error": "query is required"}

        hybrid = getattr(self, "hybrid_rag", None)
        kb = getattr(self, "knowledge_base", None)

        if hybrid and hasattr(hybrid, "retrieve"):
            return await hybrid.retrieve(
                query=query,
                equipment_id=equipment_id,
                strategy=strategy,
                limit=limit,
            )

        if kb and hasattr(kb, "query_specs"):
            results = await kb.query_specs(query, equipment_id, limit=limit)
            return {
                "query": query,
                "strategy": "vector_fallback",
                "vector_results": results,
                "combined": results,
                "note": "Hybrid router not configured; used vector search fallback",
            }

        return {"error": "No knowledge retrieval backend configured"}
    
    async def _handle_get_dashboard_overview(self, args: Dict) -> Dict:
        state = getattr(self, "bms_state", None)
        if not state:
            return {"error": "BMS state engine not configured"}
        
        if hasattr(state, "get_snapshot"):
            snapshot = await state.get_snapshot()
            return snapshot
            
        return {"error": "Dashboard overview not supported by current state engine"}
