"""
Maintenance Tool Handlers
=========================

Handlers for predictive maintenance and verification tools.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("arvis.bms.tools.maintenance")


class MaintenanceHandlerMixin:
    """Mixin providing maintenance-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "predict_maintenance": instance._handle_predict_maintenance,
            "predict_remaining_life": instance._handle_predict_remaining_life,
            "verify_maintenance_work": instance._handle_verify_maintenance_work,
            "predict_filter_degradation": instance._handle_predict_filter_degradation,
        }
    
    async def _handle_predict_maintenance(self, args: Dict) -> Dict:
        predictive_engine = getattr(self, "predictive_engine", None)
        if not predictive_engine:
            return {"error": "Predictive engine not configured or service not available"}
        
        try:
            equipment_id = args.get("equipment_id", "all")
            if hasattr(predictive_engine, "predict_maintenance"):
                prediction = await predictive_engine.predict_maintenance(equipment_id)
                return {"predictions": [prediction] if isinstance(prediction, dict) else prediction}
                
            return {
                "error": "no_data",
                "reason": "Predictive engine has no baseline data for this equipment yet. Minimum 2 weeks of sensor history required.",
                "equipment_id": equipment_id,
            }
        except Exception as e:
            logger.error(f"Maintenance prediction failed: {e}")
            return {"error": f"Prediction failed: {str(e)}"}
    
    async def _handle_predict_remaining_life(self, args: Dict) -> Dict:
        """Predict Remaining Useful Life (RUL) for equipment"""
        try:
            equipment_id = args.get("equipment_id")
            forecast_days = args.get("forecast_days", 90)
            
            if not equipment_id:
                return {"error": "equipment_id is required"}
            
            predictive_engine = getattr(self, "predictive_engine", None)
            if predictive_engine and hasattr(predictive_engine, "predict_rul"):
                return await predictive_engine.predict_rul(equipment_id, forecast_days)
            
            return {
                "error": "no_data",
                "reason": "No RUL model available for this equipment. Ensure predictive engine is configured and sensor history exists.",
                "equipment_id": equipment_id,
            }
        except Exception as e:
            logger.error(f"RUL prediction failed: {e}")
            return {"error": f"RUL prediction failed: {str(e)}"}
    
    async def _handle_verify_maintenance_work(self, args: Dict) -> Dict:
        try:
            from agent_commercial.verification_engine import verify_maintenance_work
            from agent_commercial.database import get_database
            
            db = get_database()
            work_order_id = args.get("work_order_id", "WO-UNKNOWN")
            equipment_id = args.get("equipment_id", "EQ-UNKNOWN")
            task_type = args.get("task_type", "filter_cleaning")
            
            # Try to get real work order data from database
            work_order = None
            if db and hasattr(db, "get_work_order"):
                try:
                    work_order = await db.get_work_order(work_order_id)
                except Exception as de:
                    logger.warning(f"Database error fetching work order: {de}")
            
            pre_data = {}
            post_data = {}
            
            if work_order and work_order.get("pre_snapshot") and work_order.get("post_snapshot"):
                # Use real pre/post snapshots from work order
                pre_data = work_order["pre_snapshot"]
                post_data = work_order["post_snapshot"]
            else:
                bms_state = getattr(self, "bms_state", None)
                if bms_state and args.get("use_state_history"):
                    # Try to get from state engine history
                    try:
                        points = await bms_state.get_points_by_equipment(equipment_id) if hasattr(bms_state, "get_points_by_equipment") else []
                        current_values = {p.point_id.split("/")[-1].lower(): p.value for p in points} if points else {}
                        
                        # Get historical values if available
                        hist_pre_data = {}
                        if hasattr(bms_state, "get_point_history"):
                            for point in points:
                                try:
                                    history = await bms_state.get_point_history(point.point_id, 1440)  # 24h
                                    if history:
                                        hist_pre_data[point.point_id.split("/")[-1].lower()] = history[-1][1]  # Oldest value
                                except Exception:
                                    pass
                        
                        pre_data = hist_pre_data
                        post_data = current_values
                        
                        if not pre_data:
                            pre_data = post_data  # No history, use current as both
                    except Exception as bse:
                        logger.warning(f"BMS state history fetch failed: {bse}")
                
                if not pre_data or not post_data:
                    return {
                        "error": "no_data",
                        "reason": "No pre/post telemetry snapshots found for this work order. Cannot verify maintenance without before/after sensor data.",
                        "work_order_id": work_order_id,
                        "equipment_id": equipment_id,
                    }

            result = await verify_maintenance_work(
                work_order_id=work_order_id,
                equipment_id=equipment_id,
                task_type=task_type,
                pre_data=pre_data,
                post_data=post_data,
            )
            
            return result
        except Exception as e:
            logger.error(f"Maintenance verification failed: {e}")
            return {"error": f"Verification failed: {str(e)}"}

    async def _handle_predict_filter_degradation(self, args: Dict) -> Dict:
        """Predict filter replacement timing via DP trend analysis."""
        equipment_id = args.get("equipment_id")
        predictive_engine = getattr(self, "predictive_engine", None)

        if not predictive_engine or not hasattr(predictive_engine, "filter_predictor"):
            return {"error": "Filter degradation predictor not available"}

        predictor = predictive_engine.filter_predictor

        if equipment_id:
            result = predictor.predict_degradation(equipment_id)
            filters = [result.to_dict()]
        else:
            results = predictor.scan_all_filters()
            filters = [r.to_dict() for r in results]

        critical = [f for f in filters if f["risk_level"] in ("critical", "high")]
        summary = (
            f"{len(critical)} filter(s) need attention. "
            f"Most urgent: {critical[0]['equipment_id']} — {critical[0]['recommendation']}"
            if critical else "All tracked filters within normal parameters."
        )

        return {"filters": filters, "summary": summary}
