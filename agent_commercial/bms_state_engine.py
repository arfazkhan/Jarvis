"""
BMS State Engine
================

Central state store for all BMS equipment and data points.
Thread-safe, async-compatible, with in-memory history buffer.

This is the "single source of truth" for current BMS state.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict
import logging

from agent_commercial.bms_data_model import (
    BMSDataPoint,
    Equipment,
    EquipmentType,
    EquipmentStatus,
    PointType,
    PointQuality,
    Alarm,
    AlarmState,
)

logger = logging.getLogger("arvis.bms.state")


class BMSStateEngine:
    """
    Central state store for Building Management System.
    
    Responsibilities:
    - Store current values for all data points
    - Maintain equipment registry with topology
    - Track active alarms
    - Provide query interface for ML models and API
    - Emit events on state changes (via callback)
    
    Thread Safety:
    - Uses asyncio.Lock for concurrent access
    - Safe for use with BACnet polling + API requests
    
    Example:
        >>> state = BMSStateEngine()
        >>> state.register_equipment(Equipment(
        ...     equipment_id="AHU-01",
        ...     name="Air Handler 1",
        ...     equipment_type=EquipmentType.AHU
        ... ))
        >>> state.update_point(BMSDataPoint(
        ...     point_id="AHU-01/SAT",
        ...     name="Supply Air Temp",
        ...     value=18.5,
        ...     unit="°C",
        ...     equipment_id="AHU-01"
        ... ))
        >>> current = state.get_point("AHU-01/SAT")
    """
    
    def __init__(self, history_buffer_hours: int = 24):
        """
        Initialize BMS State Engine.
        
        Args:
            history_buffer_hours: Hours of history to keep in memory
        """
        # Core state stores
        self._equipment: Dict[str, Equipment] = {}
        self._points: Dict[str, BMSDataPoint] = {}
        self._alarms: Dict[str, Alarm] = {}
        
        # Topology: building -> floor -> zone -> equipment
        self._topology: Dict[str, Dict[str, Dict[str, List[str]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        
        # History buffer settings
        self._history_buffer_hours = history_buffer_hours
        self._max_history_points = history_buffer_hours * 60  # 1-minute resolution
        
        # Event callbacks
        self._on_point_update: List[Callable] = []
        self._on_alarm: List[Callable] = []
        self._on_equipment_status_change: List[Callable] = []
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # Database persistence
        self.db = None
        
        # Statistics
        self._stats = {
            "points_updated": 0,
            "alarms_received": 0,
            "last_update": None,
        }
        
        logger.info("BMSStateEngine initialized")

    def set_database(self, db):
        """Set database for persistence."""
        self.db = db
    
    # ═══════════════════════════════════════════════════════════════════════
    # EQUIPMENT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def register_equipment(self, equipment: Equipment) -> None:
        """Register or update equipment in the state store"""
        async with self._lock:
            self._equipment[equipment.equipment_id] = equipment
            
            # Update topology if location is provided
            if equipment.location:
                self._update_topology(equipment)
            
            logger.debug(f"Registered equipment: {equipment.equipment_id}")
    
    def register_equipment_sync(self, equipment: Equipment) -> None:
        """Synchronous version for initialization"""
        self._equipment[equipment.equipment_id] = equipment
        if equipment.location:
            self._update_topology(equipment)
    
    def _update_topology(self, equipment: Equipment) -> None:
        """Parse location string and update topology index"""
        # Expected format: "Building A, Floor 3, Zone 1" or similar
        parts = [p.strip() for p in equipment.location.split(",")]
        
        building = parts[0] if len(parts) > 0 else "Unknown"
        floor = parts[1] if len(parts) > 1 else "Unknown"
        zone = parts[2] if len(parts) > 2 else "Unknown"
        
        if equipment.equipment_id not in self._topology[building][floor][zone]:
            self._topology[building][floor][zone].append(equipment.equipment_id)
    
    async def get_equipment(self, equipment_id: str) -> Optional[Equipment]:
        """Get equipment by ID"""
        async with self._lock:
            return self._equipment.get(equipment_id)
    
    def get_equipment_sync(self, equipment_id: str) -> Optional[Equipment]:
        """Synchronous version for ML models"""
        return self._equipment.get(equipment_id)
    
    async def get_all_equipment(self) -> List[Equipment]:
        """Get all registered equipment"""
        async with self._lock:
            return list(self._equipment.values())
    
    async def get_equipment_by_type(self, eq_type: EquipmentType) -> List[Equipment]:
        """Get all equipment of a specific type"""
        async with self._lock:
            return [e for e in self._equipment.values() if e.equipment_type == eq_type]
    
    async def get_equipment_by_location(
        self, 
        building: Optional[str] = None,
        floor: Optional[str] = None,
        zone: Optional[str] = None
    ) -> List[Equipment]:
        """Get equipment filtered by location"""
        async with self._lock:
            if building and floor and zone:
                eq_ids = self._topology.get(building, {}).get(floor, {}).get(zone, [])
            elif building and floor:
                eq_ids = []
                for z in self._topology.get(building, {}).get(floor, {}).values():
                    eq_ids.extend(z)
            elif building:
                eq_ids = []
                for f in self._topology.get(building, {}).values():
                    for z in f.values():
                        eq_ids.extend(z)
            else:
                return list(self._equipment.values())
            
            return [self._equipment[eid] for eid in eq_ids if eid in self._equipment]
    
    async def update_equipment_status(
        self, 
        equipment_id: str, 
        status: EquipmentStatus
    ) -> None:
        """Update equipment operational status"""
        async with self._lock:
            if equipment_id in self._equipment:
                old_status = self._equipment[equipment_id].status
                self._equipment[equipment_id].status = status
                
                if old_status != status:
                    for callback in self._on_equipment_status_change:
                        try:
                            callback(equipment_id, old_status, status)
                        except Exception as e:
                            logger.error(f"Status change callback error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # DATA POINT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def update_point(self, point: BMSDataPoint) -> None:
        """
        Update a data point value.
        
        - Stores current value
        - Adds to history buffer
        - Triggers callbacks for subscribers
        """
        async with self._lock:
            # Get existing point or use new one
            existing = self._points.get(point.point_id)
            
            if existing:
                # Update existing point
                existing.value = point.value
                existing.timestamp = point.timestamp
                existing.quality = point.quality
                existing.add_to_history(self._max_history_points)
            else:
                # Register new point
                point.add_to_history(self._max_history_points)
                self._points[point.point_id] = point
                
                # Add to equipment's point list if not already there
                if point.equipment_id and point.equipment_id in self._equipment:
                    eq = self._equipment[point.equipment_id]
                    if point.point_id not in eq.data_points:
                        eq.data_points.append(point.point_id)
            
            self._stats["points_updated"] += 1
            self._stats["last_update"] = datetime.now()
        
        # Trigger callbacks (outside lock to prevent deadlocks)
        for callback in self._on_point_update:
            try:
                callback(point)
            except Exception as e:
                logger.error(f"Point update callback error: {e}")
    
    def update_point_sync(self, point: BMSDataPoint) -> None:
        """Synchronous version for BACnet polling thread"""
        existing = self._points.get(point.point_id)
        
        if existing:
            existing.value = point.value
            existing.timestamp = point.timestamp
            existing.quality = point.quality
            existing.add_to_history(self._max_history_points)
        else:
            point.add_to_history(self._max_history_points)
            self._points[point.point_id] = point
            
            if point.equipment_id and point.equipment_id in self._equipment:
                eq = self._equipment[point.equipment_id]
                if point.point_id not in eq.data_points:
                    eq.data_points.append(point.point_id)
        
        self._stats["points_updated"] += 1
        self._stats["last_update"] = datetime.now()
    
    async def get_point(self, point_id: str) -> Optional[BMSDataPoint]:
        """Get a data point by ID"""
        async with self._lock:
            return self._points.get(point_id)
    
    def get_point_sync(self, point_id: str) -> Optional[BMSDataPoint]:
        """Synchronous version for ML models"""
        return self._points.get(point_id)
    
    async def get_points_by_equipment(self, equipment_id: str) -> List[BMSDataPoint]:
        """Get all data points for an equipment"""
        async with self._lock:
            return [p for p in self._points.values() if p.equipment_id == equipment_id]
    
    async def get_points_by_type(self, point_type: PointType) -> List[BMSDataPoint]:
        """Get all data points of a specific type"""
        async with self._lock:
            return [p for p in self._points.values() if p.point_type == point_type]
    
    async def get_current_values(
        self, 
        point_ids: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """Get current values for multiple points"""
        async with self._lock:
            if point_ids:
                return {
                    pid: self._points[pid].value 
                    for pid in point_ids 
                    if pid in self._points and self._points[pid].value is not None
                }
            else:
                return {
                    pid: p.value 
                    for pid, p in self._points.items() 
                    if p.value is not None
                }
    
    async def get_point_history(
        self, 
        point_id: str, 
        minutes: int = 60
    ) -> List[tuple]:
        """Get historical values for a point"""
        async with self._lock:
            point = self._points.get(point_id)
            if point:
                cutoff = datetime.now().timestamp() - (minutes * 60)
                return [(t, v) for t, v in point.history if t.timestamp() > cutoff]
            return []
    
    # ═══════════════════════════════════════════════════════════════════════
    # ALARM MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def add_alarm(self, alarm: Alarm) -> None:
        """Add or update an alarm"""
        async with self._lock:
            self._alarms[alarm.alarm_id] = alarm
            
            # Add to equipment's active alarm list
            if alarm.equipment_id and alarm.equipment_id in self._equipment:
                eq = self._equipment[alarm.equipment_id]
                if alarm.alarm_id not in eq.active_alarm_ids:
                    eq.active_alarm_ids.append(alarm.alarm_id)
            
            self._stats["alarms_received"] += 1
        
        # Trigger callbacks
        for callback in self._on_alarm:
            try:
                callback(alarm)
            except Exception as e:
                logger.error(f"Alarm callback error: {e}")
    
    async def acknowledge_alarm(self, alarm_id: str, by: str) -> bool:
        """Acknowledge an alarm (Async & Persistent)"""
        async with self._lock:
            if alarm_id in self._alarms:
                alarm = self._alarms[alarm_id]
                alarm.state = AlarmState.ACKNOWLEDGED
                alarm.acknowledged_at = datetime.now()
                alarm.acknowledged_by = by
                
                # Persist to database if available
                if self.db:
                    try:
                        await self.db.update_alarm_state(
                            alarm_id=alarm_id,
                            state=AlarmState.ACKNOWLEDGED,
                            acknowledged_by=by,
                            acknowledged_at=alarm.acknowledged_at
                        )
                    except Exception as e:
                        logger.error(f"Failed to persist alarm acknowledgment: {e}")
                
                return True
            return False
    
    async def resolve_alarm(self, alarm_id: str) -> bool:
        """Mark an alarm as resolved"""
        async with self._lock:
            if alarm_id in self._alarms:
                alarm = self._alarms[alarm_id]
                alarm.state = AlarmState.RESOLVED
                alarm.resolved_at = datetime.now()
                
                # Remove from equipment's active list
                if alarm.equipment_id and alarm.equipment_id in self._equipment:
                    eq = self._equipment[alarm.equipment_id]
                    if alarm_id in eq.active_alarm_ids:
                        eq.active_alarm_ids.remove(alarm_id)
                
                return True
            return False
    
    async def get_active_alarms(self) -> List[Alarm]:
        """Get all active (unresolved) alarms"""
        async with self._lock:
            return [
                a for a in self._alarms.values() 
                if a.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)
            ]
    
    async def get_alarms_by_equipment(self, equipment_id: str) -> List[Alarm]:
        """Get all alarms for an equipment"""
        async with self._lock:
            return [a for a in self._alarms.values() if a.equipment_id == equipment_id]
    
    # ═══════════════════════════════════════════════════════════════════════
    # SNAPSHOT & CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def get_snapshot(self) -> Dict[str, Any]:
        """
        Get current state snapshot.
        Used by CognitiveLoop for analysis.
        """
        async with self._lock:
            active_alarms = [
                a for a in self._alarms.values() 
                if a.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)
            ]
            
            return {
                "timestamp": datetime.now().isoformat(),
                "equipment_count": len(self._equipment),
                "point_count": len(self._points),
                "active_alarm_count": len(active_alarms),
                "equipment_by_status": self._count_by_status(),
                "current_values": {
                    pid: p.value for pid, p in self._points.items() if p.value is not None
                },
                "active_alarms": [a.to_dict() for a in active_alarms[:20]],  # Top 20
                "stats": self._stats.copy(),
            }
    
    def _count_by_status(self) -> Dict[str, int]:
        """Count equipment by operational status"""
        counts = defaultdict(int)
        for eq in self._equipment.values():
            counts[eq.status.value] += 1
        return dict(counts)
    
    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        """Register callback for point updates"""
        self._on_point_update.append(callback)
    
    def on_alarm(self, callback: Callable[[Alarm], None]) -> None:
        """Register callback for new alarms"""
        self._on_alarm.append(callback)
    
    def on_equipment_status_change(
        self, 
        callback: Callable[[str, EquipmentStatus, EquipmentStatus], None]
    ) -> None:
        """Register callback for equipment status changes"""
        self._on_equipment_status_change.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════
    
    async def cleanup_old_history(self) -> int:
        """Remove history entries older than buffer limit"""
        async with self._lock:
            cutoff = datetime.now() - timedelta(hours=self._history_buffer_hours)
            cutoff_ts = cutoff.timestamp()
            cleaned = 0
            
            for point in self._points.values():
                original_len = len(point.history)
                point.history = [
                    (t, v) for t, v in point.history if t.timestamp() > cutoff_ts
                ]
                cleaned += original_len - len(point.history)
            
            return cleaned
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get state engine statistics"""
        async with self._lock:
            return {
                **self._stats,
                "equipment_count": len(self._equipment),
                "point_count": len(self._points),
                "alarm_count": len(self._alarms),
                "active_alarm_count": len([
                    a for a in self._alarms.values() 
                    if a.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)
                ]),
            }
