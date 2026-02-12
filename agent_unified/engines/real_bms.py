from typing import List, Dict, Any, Optional
import logging
from agent_unified.engines.bacnet import BACnetAdapter, BACnetPoint
from agent_unified.schema import BMSDataPoint

logger = logging.getLogger("arvis.engines.real_bms")

class RealBMS:
    """
    Real BMS Engine that wraps BACnetAdapter to provide standard BMS data interface.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        # Configure Adapter
        local_address = "0.0.0.0"
        device_id = 999
        port = 47808
        
        if config and "bacnet" in config:
            bc = config["bacnet"]
            local_address = bc.get("local_address", "0.0.0.0")
            port = bc.get("port", 47808)
            device_id = bc.get("device_id", 999)
            
        self.adapter = BACnetAdapter(
            local_address=local_address,
            local_port=port,
            device_id=device_id
        )
        
        # Load point definitions
        if config:
            self.adapter.load_points_from_config(config.get("bacnet", {}))
            
        # Instance level cache
        self._value_cache: Dict[str, float] = {}
        self._active_alarms: List[Dict] = []
        
        # Register callbacks
        self.adapter.on_point_update(self.update_cache)
        self.adapter.on_alarm(self._handle_alarm)

        # Store equipment metadata (in a real app, from DB or config)
        # For YABE demo, we hardcode equipment based on config presence
        self._equipment_registry = {} 
        if config:
            self._parse_equipment_from_config(config.get("bacnet", {}).get("points", []))

    async def connect(self):
        """Connect to BACnet"""
        logger.info("Connecting to Real BMS (BACnet)...")
        if await self.adapter.connect():
            # Start polling or discovery
            await self.adapter.discover_devices()
            self.adapter.start_polling(interval_seconds=5) # Fast poll for demo
            return True
        return False
        
    async def disconnect(self):
        await self.adapter.disconnect()

    def _parse_equipment_from_config(self, points: List[Dict]):
        """Infer equipment list from point definitions"""
        for p in points:
            eq_id = p.get("equipment_id")
            if eq_id and eq_id not in self._equipment_registry:
                # Infer type from ID (hacky but works for demo)
                eq_type = "ahu" if "AHU" in eq_id else "chiller" if "CH" in eq_id else "meter"
                self._equipment_registry[eq_id] = {
                    "id": eq_id,
                    "name": f"Equipment {eq_id}",
                    "type": eq_type,
                    "status": "running", # Default assumption until we read a status point
                    "location": "Plant Room"
                }

    # ═══════════════════════════════════════════════════════════
    # STANDARD BMS INTERFACE (Used by BMS Tools)
    # ═══════════════════════════════════════════════════════════

    def get_equipment(self, eq_id: str):
        data = self._equipment_registry.get(eq_id)
        if not data: return None
        
        # Create object-like response
        class EqObj: 
            pass
        obj = EqObj()
        obj.equipment_id = data["id"]
        obj.name = data["name"]
        obj.eq_type = data["type"]
        obj.status = data["status"]
        obj.location = data["location"]
        return obj

    def get_points_by_equipment(self, eq_id: str) -> List[Any]:
        """Get LATEST READINGS for equipment"""
        # Note: In a real system, we'd read from DB/cache. 
        # Here we ask adapter for configured points matching ID.
        # Ideally we read fresh values or cached values. adapter.read_point does network call.
        
        points = []
        for pid, p_config in self.adapter.points.items():
            if p_config.equipment_id == eq_id:
                class Pt: pass
                obj = Pt()
                obj.point_id = pid
                obj.name = p_config.point_name
                obj.unit = p_config.unit
                obj.value = 0.0 # Default
                
                val = self._value_cache.get(pid)
                if val is not None:
                    obj.value = val
                
                points.append(obj)
        return points

    def get_active_alarms(self, priority_filter=None):
        """Get list of active alarms"""
        # Return objects as expected by Alarms Tool
        res = []
        for a in self._active_alarms:
            # Check filter
            # Assuming 'a' is a dict or object with priority
            if priority_filter:
                prio = a.get("priority", "low")
                if priority_filter.lower() not in prio.lower():
                    continue
            
            class Alm: pass
            obj = Alm()
            # method to return dict rep
            obj.to_dict = lambda x=a: x
            res.append(obj)
        return res
        
    def _handle_alarm(self, alarm):
        """Process incoming BACnet alarm"""
        # Convert to simple dict
        alarm_data = {
            "id": f"ALM-{len(self._active_alarms)+1}", 
            "priority": "critical" if alarm.severity == "CRITICAL" else "low", # map enum
            "message": alarm.message if hasattr(alarm, 'message') else str(alarm),
            "status": "active",
            "timestamp": str(alarm.timestamp)
        }
        self._active_alarms.append(alarm_data)
        logger.warning(f"New Alarm: {alarm_data['message']}")

    def get_all_equipment(self):
        res = []
        for k, v in self._equipment_registry.items():
            class Eq: pass
            obj = Eq(); obj.equipment_id=v["id"]; obj.eq_type=v["type"]; obj.status=v["status"]
            res.append(obj)
        return res

    
    def update_cache(self, point: BMSDataPoint):
        self._value_cache[point.point_id] = point.value
