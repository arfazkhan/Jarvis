"""
Energy Tool Handlers
====================

Handlers for energy analysis and cost calculation tools.
"""

import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger("arvis.bms.tools.energy")

# Safe imports for modular standalone operation
try:
    from agent_commercial.cost_engine import check_cost_impact, get_current_burn_rate
except ImportError:
    check_cost_impact = None
    get_current_burn_rate = None

try:
    from agent_commercial.virtual_sensors import (
        VirtualOccupancySensor,
        estimate_zone_occupancy,
        OccupancyLevel,
        VirtualSATSensor,
        estimate_virtual_sat,
        get_registry as get_virtual_sensor_registry,
    )
except ImportError:
    VirtualOccupancySensor = None
    estimate_zone_occupancy = None
    OccupancyLevel = None
    VirtualSATSensor = None
    estimate_virtual_sat = None
    get_virtual_sensor_registry = None

try:
    from agent_commercial.database import get_database
except ImportError:
    get_database = None


class EnergyHandlerMixin:
    """Mixin providing energy-related tool handlers."""
    
    @classmethod
    def get_handlers(cls, instance) -> dict:
        """Return dict of tool name -> handler method."""
        return {
            "analyze_energy": instance._handle_analyze_energy,
            "get_energy_anomalies": instance._handle_get_energy_anomalies,
            "check_cost_impact": instance._handle_check_cost_impact,
            "get_burn_rate": instance._handle_get_burn_rate,
            "find_ghost_spaces": instance._handle_find_ghost_spaces,
            "estimate_zone_occupancy": instance._handle_estimate_zone_occupancy,
            "estimate_virtual_sat": instance._handle_estimate_virtual_sat,
            "get_virtual_sensor_reading": instance._handle_get_virtual_sensor_reading,
        }
    
    async def _handle_analyze_energy(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        try:
            summary = self.energy_analyzer.get_summary()
            if isinstance(summary, dict):
                # Normalize to schema keys: total_kwh, cost_qar, anomalies
                if summary.get("total_kwh") is None:
                    summary["total_kwh"] = (
                        summary.get("total_energy_kwh")
                        or summary.get("energy_kwh")
                        or summary.get("kwh")
                        or 0.0
                    )
                if summary.get("cost_qar") is None:
                    summary["cost_qar"] = (
                        summary.get("total_cost_qar")
                        or summary.get("cost")
                        or 0.0
                    )
                if summary.get("anomalies") is None:
                    summary["anomalies"] = (
                        summary.get("waste_patterns")
                        or summary.get("patterns")
                        or []
                    )
            return summary
        except Exception as e:
            logger.error(f"Error in analyze_energy: {e}")
            return {"error": f"Analysis error: {str(e)}"}
    
    async def _handle_get_energy_anomalies(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        try:
            patterns = self.energy_analyzer.identify_waste_patterns()
            pdicts = [(p.to_dict() if hasattr(p, "to_dict") else p) for p in patterns]
            # Aggregate for schema: total_waste_kwh, potential_savings_qar
            total_waste = 0.0
            total_savings = 0.0
            for p in pdicts:
                if isinstance(p, dict):
                    total_waste += float(p.get("waste_kwh") or p.get("wasted_kwh") or 0) or 0.0
                    total_savings += float(p.get("savings_qar") or p.get("potential_savings_qar") or 0) or 0.0
            return {
                "count": len(pdicts),
                "patterns": pdicts,
                # Schema keys
                "anomalies": pdicts,
                "anomaly_count": len(pdicts),
                "total_waste_kwh": round(total_waste, 2),
                "potential_savings_qar": round(total_savings, 2),
            }
        except Exception as e:
            logger.error(f"Error in get_energy_anomalies: {e}")
            return {"error": f"Anomaly detection error: {str(e)}"}
    
    async def _handle_check_cost_impact(self, args: Dict) -> Dict:
        """Calculate financial impact of temperature change"""
        current_temp = args.get("current_temp")
        target_temp = args.get("target_temp")
        zone_id = args.get("zone_id", "default")
        
        if current_temp is None or target_temp is None:
            return {"error": "current_temp and target_temp are required"}
            
        if check_cost_impact is None:
            return {"error": "Cost engine module not available"}
            
        try:
            result = check_cost_impact(
                current_temp=float(current_temp),
                target_temp=float(target_temp),
                zone_id=zone_id,
            )
            return result
        except Exception as e:
            logger.error(f"Error in check_cost_impact: {e}")
            return {"error": f"Cost calculation error: {str(e)}"}
    
    async def _handle_get_burn_rate(self, args: Dict) -> Dict:
        """Get current building burn rate in QAR/hour"""
        if get_current_burn_rate is None:
            return {"error": "Cost engine module not available"}
            
        try:
            total_kw = args.get("total_kw")
            if total_kw is None:
                 # Try to get from state
                 total_kw = 450 # Default
                 
            return get_current_burn_rate(float(total_kw))
        except Exception as e:
            logger.error(f"Error in get_burn_rate: {e}")
            return {"error": f"Burn rate error: {str(e)}"}
    
    async def _handle_find_ghost_spaces(self, args: Dict) -> Dict:
        """Find rooms being cooled but empty - using real zone data"""
        if VirtualOccupancySensor is None:
            return {"error": "Virtual sensors module not available"}
            
        try:
            db = self.bms_state if hasattr(self.bms_state, "get_all_zones") else (get_database() if get_database else None)
            if not db:
                return {"error": "Database/BMS state not available"}
            
            floor_filter = args.get("floor_filter")
            
            # Get zones from database with current sensor values
            zones = await db.get_all_zones()
            
            if floor_filter:
                zones = [z for z in zones if z.get("floor") == floor_filter]
            
            if not zones:
                return {
                    "ghost_operations": [],
                    "waste_estimate_qar_day": 0,
                    "note": "No zones configured. Add zones via the database.",
                    # Schema keys
                    "ghost_spaces": [],
                    "total_ghost_count": 0,
                    "total_waste_kwh_day": 0.0,
                    "potential_savings_qar_month": 0.0,
                }
            
            sensor = VirtualOccupancySensor()
            ghost_operations = []
            total_waste = 0
            
            for zone_config in zones:
                zone_id = zone_config.get("zone_id")
                
                # Get current sensor values from database
                zone = await db.get_zone_with_current_values(zone_id)
                if not zone:
                    continue
                
                # Skip if we don't have CO2 data
                co2_ppm = zone.get("co2_ppm")
                if co2_ppm is None:
                    co2_ppm = 410  # Default to ambient if no sensor
                
                vav_pct = zone.get("vav_damper_pct")
                if vav_pct is None:
                    vav_pct = 50
                    
                light_on = zone.get("light_status")
                if light_on is None:
                    light_on = False
                
                # Estimate occupancy
                estimate = sensor.estimate_occupancy(
                    zone_id=zone_id,
                    co2_ppm=co2_ppm,
                    vav_damper_pct=vav_pct,
                    light_status=light_on,
                )
                
                # Check for ghost operation (scheduled occupied but actually empty)
                now = datetime.now()
                is_work_hours = now.weekday() < 5 and 8 <= now.hour < 18
                schedule_status = "OCCUPIED" if is_work_hours else "UNOCCUPIED"
                
                ghost = sensor.detect_ghost_operation(
                    zone_id=zone_id,
                    zone_name=zone.get("name", zone_id),
                    schedule_status=schedule_status,
                    occupancy_estimate=estimate,
                    zone_load_kw=zone.get("load_kw", 2.0),
                )
                
                if ghost:
                    ghost_operations.append({
                        "zone_id": ghost.zone_id,
                        "zone_name": ghost.zone_name,
                        "waste_qar_hour": ghost.waste_qar_per_hour,
                        "occupancy_probability": ghost.occupancy_probability,
                        "recommendation": ghost.recommendation,
                    })
                    total_waste += ghost.waste_qar_per_hour * 24  # Daily waste
            
            return {
                "ghost_operations": ghost_operations,
                "zones_checked": len(zones),
                "waste_estimate_qar_day": round(total_waste, 2),
                "potential_monthly_savings": round(total_waste * 30, 2),
                # Schema keys: ghost_spaces, total_ghost_count, total_waste_kwh_day,
                # potential_savings_qar_month
                "ghost_spaces": ghost_operations,
                "total_ghost_count": len(ghost_operations),
                "total_waste_kwh_day": round(total_waste, 2),
                "potential_savings_qar_month": round(total_waste * 30, 2),
            }
        except Exception as e:
            logger.error(f"Error in find_ghost_spaces: {e}")
            return {
                "error": f"Ghost space detection error: {str(e)}",
                "ghost_operations": [],
                "ghost_spaces": [],
                "total_ghost_count": 0,
                "total_waste_kwh_day": 0.0,
                "potential_savings_qar_month": 0.0,
            }
    
    async def _handle_estimate_zone_occupancy(self, args: Dict) -> Dict:
        """Estimate zone occupancy from BMS data"""
        zone_id = args.get("zone_id")
        if not zone_id:
            return {"error": "zone_id is required"}
            
        if estimate_zone_occupancy is None:
            return {"error": "Virtual sensors module not available"}
            
        try:
            res = estimate_zone_occupancy(
                zone_id=zone_id,
                co2_ppm=args.get("co2_ppm", 420),
                vav_damper_pct=args.get("vav_damper_pct", 50),
                light_status=args.get("light_status", True),
            )
            if isinstance(res, dict):
                # Schema keys: occupancy_probability, occupancy_level,
                # estimated_occupants, method_used
                prob = res.get("occupancy_probability")
                if prob is None:
                    prob = res.get("probability") or res.get("occupancy_estimate") or 0.0
                    res["occupancy_probability"] = prob
                if res.get("occupancy_level") is None:
                    res["occupancy_level"] = (
                        res.get("level")
                        or ("occupied" if (prob or 0) >= 0.5 else "vacant")
                    )
                if res.get("estimated_occupants") is None:
                    res["estimated_occupants"] = res.get("occupants") or res.get("count") or 0
                if res.get("method_used") is None:
                    res["method_used"] = res.get("method") or "co2_vav_light_fusion"
            return res
        except Exception as e:
            logger.error(f"Error in estimate_zone_occupancy: {e}")
            return {"error": f"Occupancy estimation error: {str(e)}"}

    async def _handle_estimate_virtual_sat(self, args: Dict) -> Dict:
        """Derive supply air temperature from existing BMS data (no new sensor needed)."""
        equipment_id = args.get("equipment_id")
        if not equipment_id:
            return {"error": "equipment_id is required"}

        if VirtualSATSensor is None:
            return {"error": "Virtual sensors module not available"}

        # Try to enrich from live BMS state if available
        bms_state = getattr(self, "bms_state", None)
        enriched = dict(args)

        if bms_state and hasattr(bms_state, "get_points_by_equipment"):
            try:
                import asyncio
                points = await bms_state.get_points_by_equipment(equipment_id)
                for p in points:
                    pid = p.point_id.split("/")[-1].upper()
                    if p.value is None:
                        continue
                    if pid == "MAT":
                        enriched.setdefault("mixed_air_temp_c", p.value)
                    elif pid == "RAT":
                        enriched.setdefault("return_air_temp_c", p.value)
                    elif pid in ("CLG_VLV", "COOL_VLV", "CV"):
                        enriched.setdefault("cooling_valve_pct", p.value)
                    elif pid in ("SF_SPD", "FAN_SPD", "FAN_SPEED"):
                        enriched.setdefault("fan_speed_pct", p.value)
                    elif pid in ("SA_FLOW", "SAF", "AIRFLOW"):
                        enriched.setdefault("airflow_m3h", p.value)
                    elif pid == "SAT":
                        enriched["actual_sat_c"] = p.value
            except Exception as e:
                logger.debug(f"BMS enrichment for virtual SAT failed: {e}")

        try:
            return estimate_virtual_sat(
                equipment_id=equipment_id,
                mixed_air_temp_c=enriched.get("mixed_air_temp_c"),
                cooling_valve_pct=enriched.get("cooling_valve_pct"),
                airflow_m3h=enriched.get("airflow_m3h"),
                rated_cooling_kw=enriched.get("rated_cooling_kw"),
                return_air_temp_c=enriched.get("return_air_temp_c"),
                fan_speed_pct=enriched.get("fan_speed_pct"),
            )
        except Exception as e:
            logger.error(f"Virtual SAT estimation error: {e}")
            return {"error": f"Virtual SAT estimation failed: {str(e)}"}

    async def _handle_get_virtual_sensor_reading(self, args: Dict) -> Dict:
        """Query any registered virtual sensor by ID via the VirtualSensorRegistry."""
        sensor_id = args.get("sensor_id")
        if not sensor_id:
            return {"error": "sensor_id is required"}

        if get_virtual_sensor_registry is None:
            return {"error": "Virtual sensors module not available"}

        registry = get_virtual_sensor_registry()

        if sensor_id not in registry:
            return {"error": f"Virtual sensor '{sensor_id}' not registered", "sensor_id": sensor_id}

        # Build kwargs for the read call
        kwargs: Dict[str, Any] = {}
        equipment_id_override = args.get("equipment_id")
        if equipment_id_override:
            kwargs["equipment_id"] = equipment_id_override

        # Enrich from live BMS state where possible
        bms_state = getattr(self, "bms_state", None)
        all_meta = {m["sensor_id"]: m for m in registry.get_all_registered()}
        meta = all_meta.get(sensor_id, {})
        primary_equipment = equipment_id_override or (meta.get("equipment_ids") or [None])[0]

        if bms_state and primary_equipment and hasattr(bms_state, "get_points_by_equipment"):
            try:
                import asyncio
                points = await bms_state.get_points_by_equipment(primary_equipment)
                sensor_type = meta.get("sensor_type", "")
                for p in points:
                    if p.value is None:
                        continue
                    pid = p.point_id.split("/")[-1].upper()
                    if sensor_type == "sat":
                        if pid == "MAT":
                            kwargs.setdefault("mixed_air_temp_c", p.value)
                        elif pid == "RAT":
                            kwargs.setdefault("return_air_temp_c", p.value)
                        elif pid in ("CLG_VLV", "COOL_VLV", "CV"):
                            kwargs.setdefault("cooling_valve_pct", p.value)
                        elif pid in ("SF_SPD", "FAN_SPD", "FAN_SPEED"):
                            kwargs.setdefault("fan_speed_pct", p.value)
                        elif pid in ("SA_FLOW", "SAF", "AIRFLOW"):
                            kwargs.setdefault("airflow_m3h", p.value)
                    elif sensor_type == "occupancy":
                        if pid == "CO2":
                            kwargs.setdefault("co2_ppm", p.value)
                        elif pid in ("VAV", "VAV_PCT", "DAMPER"):
                            kwargs.setdefault("vav_damper_pct", p.value)
                        elif pid in ("LIGHT", "LIGHTS"):
                            kwargs.setdefault("light_status", bool(p.value))
            except Exception as e:
                logger.debug(f"BMS enrichment for virtual sensor {sensor_id} failed: {e}")

        try:
            result = registry.read(sensor_id, **kwargs)
            return result
        except Exception as e:
            logger.error(f"get_virtual_sensor_reading error for {sensor_id}: {e}")
            return {"error": f"Virtual sensor read failed: {str(e)}", "sensor_id": sensor_id}
