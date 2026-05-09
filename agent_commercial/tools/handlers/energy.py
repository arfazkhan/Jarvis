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
        OccupancyLevel
    )
except ImportError:
    VirtualOccupancySensor = None
    estimate_zone_occupancy = None
    OccupancyLevel = None

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
        }
    
    async def _handle_analyze_energy(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        try:
            return self.energy_analyzer.get_summary()
        except Exception as e:
            logger.error(f"Error in analyze_energy: {e}")
            return {"error": f"Analysis error: {str(e)}"}
    
    async def _handle_get_energy_anomalies(self, args: Dict) -> Dict:
        if not self.energy_analyzer:
            return {"error": "Energy analyzer not configured"}
        
        try:
            patterns = self.energy_analyzer.identify_waste_patterns()
            return {
                "count": len(patterns),
                "patterns": [ (p.to_dict() if hasattr(p, "to_dict") else p) for p in patterns ]
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
                    "note": "No zones configured. Add zones via the database."
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
            }
        except Exception as e:
            logger.error(f"Error in find_ghost_spaces: {e}")
            return {"error": f"Ghost space detection error: {str(e)}", "ghost_operations": []}
    
    async def _handle_estimate_zone_occupancy(self, args: Dict) -> Dict:
        """Estimate zone occupancy from BMS data"""
        zone_id = args.get("zone_id")
        if not zone_id:
            return {"error": "zone_id is required"}
            
        if estimate_zone_occupancy is None:
            return {"error": "Virtual sensors module not available"}
            
        try:
            return estimate_zone_occupancy(
                zone_id=zone_id,
                co2_ppm=args.get("co2_ppm", 420),
                vav_damper_pct=args.get("vav_damper_pct", 50),
                light_status=args.get("light_status", True),
            )
        except Exception as e:
            logger.error(f"Error in estimate_zone_occupancy: {e}")
            return {"error": f"Occupancy estimation error: {str(e)}"}
