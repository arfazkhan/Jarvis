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


# Fix 8: Telemetry source priority. Lower index = higher priority.
_SOURCE_PRIORITY = {
    "BMS_HISTORIAN": 0,
    "LIVE_BMS_SNAPSHOT": 1,
    "INFERRED": 2,
}


def _source_priority_allows(existing, incoming, all_points_dict) -> bool:
    """
    Return True if incoming point's source is >= existing source priority.
    Logs a conflict and returns False otherwise. Also surfaces STATUS-field
    conflicts across streams within the same session.
    """
    existing_src = (getattr(existing, "source", None) or "").upper() or None
    incoming_src = (getattr(incoming, "source", None) or "").upper() or None
    # Without source metadata we can't enforce priority; allow update.
    if existing_src is None or incoming_src is None:
        return True
    ex_rank = _SOURCE_PRIORITY.get(existing_src, 99)
    in_rank = _SOURCE_PRIORITY.get(incoming_src, 99)
    if in_rank > ex_rank:
        # Detect STATUS-field conflict for richer log
        eq = getattr(incoming, "equipment_id", "") or getattr(existing, "equipment_id", "")
        if "STATUS" in (getattr(incoming, "point_id", "") or "").upper() and existing.value != incoming.value:
            logger.warning(
                f"[BMS] STATUS conflict on {eq}: keeping {existing.value} from {existing_src} "
                f"(rejected {incoming.value} from {incoming_src})"
            )
        else:
            logger.info(
                f"[BMS] Source priority reject: {incoming_src} cannot overwrite {existing_src} "
                f"on point {getattr(incoming, 'point_id', '?')}"
            )
        return False
    return True


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
        self._on_alarm_resolved: List[Callable] = []
        self._on_equipment_status_change: List[Callable] = []
        
        # Thread safety
        self._lock = asyncio.Lock()
        
        # Database persistence
        self.db = None
        
        # Suppressed points for sensor exclusion
        self.suppressed_points = set()
        
        # Statistics
        self._stats = {
            "points_updated": 0,
            "alarms_received": 0,
            "last_update": None,
        }
        
        logger.info("BMSStateEngine initialized")

    def suppress_point(self, point_id: str) -> None:
        """Excludes a point from active updates (suppressed broken sensor)."""
        self.suppressed_points.add(point_id)
        logger.info(f"Point {point_id} is now SUPPRESSED (marked as broken sensor)")

    def unsuppress_point(self, point_id: str) -> None:
        """Removes a point from suppression list."""
        if point_id in self.suppressed_points:
            self.suppressed_points.remove(point_id)
            logger.info(f"Point {point_id} is now UNSUPPRESSED")

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary of the current BMS state."""
        return {
            "equipment_count": len(self._equipment),
            "points_count": len(self._points),
            "alarm_count": len(self._alarms),
            "stats": self._stats
        }

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
        # Exclude suppressed/broken sensors from the digital twin state
        if hasattr(self, "suppressed_points") and point.point_id in self.suppressed_points:
            from agent_commercial.bms_data_model import PointQuality
            point.quality = PointQuality.BAD
            return

        async with self._lock:
            # Get existing point or use new one
            existing = self._points.get(point.point_id)

            # Fix 8: Source priority — BMS_HISTORIAN > LIVE_BMS_SNAPSHOT > INFERRED
            if existing and not _source_priority_allows(existing, point, self._points):
                return

            if existing:
                # Update existing point
                existing.value = point.value
                existing.timestamp = point.timestamp
                existing.quality = point.quality
                # Track source if provided so subsequent updates can compare
                _new_src = getattr(point, "source", None)
                if _new_src is not None:
                    try:
                        setattr(existing, "source", _new_src)
                    except Exception:
                        pass
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

        # Trigger callbacks (outside lock to prevent deadlocks).
        # Pass the canonical stored point — the one with accumulated history —
        # so downstream consumers (AnomalyWatchdog, etc.) see full history,
        # not the bare incoming point with only a single value entry.
        canonical_point = self._points.get(point.point_id, point)
        for callback in self._on_point_update:
            try:
                callback(canonical_point)
            except Exception as e:
                logger.error(f"Point update callback error: {e}")
    
    def update_point_sync(self, point: BMSDataPoint) -> None:
        """Synchronous version for BACnet polling thread"""
        existing = self._points.get(point.point_id)

        # Fix 8: Source priority enforcement
        if existing and not _source_priority_allows(existing, point, self._points):
            return

        if existing:
            existing.value = point.value
            existing.timestamp = point.timestamp
            existing.quality = point.quality
            _new_src = getattr(point, "source", None)
            if _new_src is not None:
                try:
                    setattr(existing, "source", _new_src)
                except Exception:
                    pass
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
        """Get historical values for a point (in-memory buffer, falls back to DB)."""
        async with self._lock:
            point = self._points.get(point_id)
            if point:
                # Determine simulated reference time from max timestamp of points
                sim_now = datetime.now()
                if self._points:
                    valid_ts = []
                    for p in self._points.values():
                        ts = getattr(p, 'timestamp', None)
                        if ts:
                            if ts.tzinfo is not None:
                                ts = ts.replace(tzinfo=None)
                            valid_ts.append(ts)
                    if valid_ts:
                        sim_now = max(valid_ts)
                cutoff = sim_now.timestamp() - (minutes * 60)
                
                # Point history contains (dt_object, value_float)
                result = []
                for t, v in point.history:
                    t_naive = t.replace(tzinfo=None) if t.tzinfo is not None else t
                    if t_naive.timestamp() > cutoff:
                        result.append((t, v))
                if result:
                    return result
        # Fallback: query persistent database if available
        _db = getattr(self, "db", None)
        if _db and hasattr(_db, "get_point_history"):
            try:
                hours = max(1, minutes // 60)
                db_result = await _db.get_point_history(point_id, hours=hours)
                if db_result:
                    return [(r["timestamp"], r["value"]) if isinstance(r, dict)
                            else r for r in db_result]
            except Exception:
                pass
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
                import asyncio, inspect
                if inspect.iscoroutinefunction(callback):
                    asyncio.ensure_future(callback(alarm))
                else:
                    callback(alarm)
            except Exception as e:
                logger.error(f"Alarm callback error: {e}")
    
    async def acknowledge_alarm(self, alarm_id: str, by: str, note: Optional[str] = None) -> bool:
        """Acknowledge an alarm (Async & Persistent). Optional note appended to alarm record."""
        async with self._lock:
            if alarm_id in self._alarms:
                alarm = self._alarms[alarm_id]
                alarm.state = AlarmState.ACKNOWLEDGED
                alarm.acknowledged_at = datetime.now()
                alarm.acknowledged_by = by
                if note:
                    # Append note to alarm record (best-effort, falls back to message)
                    try:
                        _existing_note = getattr(alarm, "ack_note", "") or ""
                        _combined = (_existing_note + " | " + note) if _existing_note else note
                        setattr(alarm, "ack_note", _combined)
                    except Exception:
                        try:
                            alarm.message = (alarm.message or "") + f"\n[ack note: {note}]"
                        except Exception:
                            pass

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
                
                # Persist to database if available
                if self.db:
                    try:
                        await self.db.update_alarm_state(
                            alarm_id=alarm_id,
                            state=AlarmState.RESOLVED,
                            resolved_at=alarm.resolved_at
                        )
                    except Exception as e:
                        logger.error(f"Failed to persist alarm resolution: {e}")

                # Fire resolution callbacks (e.g. cognitive loop → skillbook write)
                resolved_alarm = alarm
                for cb in self._on_alarm_resolved:
                    try:
                        cb({
                            "type": "bms_alarm_resolved",
                            "payload": {
                                "alarm": {
                                    "alarm_id": alarm_id,
                                    "equipment_id": resolved_alarm.equipment_id,
                                    "alarm_type": resolved_alarm.alarm_type
                                        if hasattr(resolved_alarm, "alarm_type") else "unknown",
                                    "message": resolved_alarm.message
                                        if hasattr(resolved_alarm, "message") else "",
                                },
                                "resolution_summary": (
                                    f"{resolved_alarm.equipment_id} alarm resolved: "
                                    + (resolved_alarm.message if hasattr(resolved_alarm, "message") else alarm_id)
                                ),
                            },
                        })
                    except Exception as _cb_err:
                        logger.warning(f"alarm_resolved callback error: {_cb_err}")

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
    
    def on_alarm_resolved(self, callback: Callable[[dict], None]) -> None:
        """Register callback fired when an alarm is resolved. Payload is the event dict."""
        self._on_alarm_resolved.append(callback)

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
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get summary of current building state."""
        return await self.get_stats()
        
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

    # ═══════════════════════════════════════════════════════════════════════
    # PERSISTENCE — Snapshot & Restore for Warm-Start
    # ═══════════════════════════════════════════════════════════════════════

    async def take_snapshot(self) -> None:
        """Persist current state to database for warm-start recovery."""
        if not self.db:
            return

        try:
            import json
            async with self._lock:
                equipment_data = []
                for eq in self._equipment.values():
                    equipment_data.append({
                        "equipment_id": eq.equipment_id,
                        "name": eq.name,
                        "equipment_type": eq.equipment_type.value,
                        "status": eq.status.value,
                        "location": eq.location or "",
                        "runtime_hours": eq.runtime_hours or 0,
                        "efficiency": (eq.efficiency * 100) if eq.efficiency else None,
                        "parent_equipment_id": eq.parent_equipment_id or "",
                    })

                points_data = []
                for p in self._points.values():
                    if p.value is not None:
                        points_data.append({
                            "point_id": p.point_id,
                            "equipment_id": p.equipment_id or "",
                            "value": p.value,
                            "unit": p.unit or "",
                            "timestamp": p.timestamp.isoformat() if p.timestamp else datetime.now().isoformat(),
                        })

                alarms_data = []
                for a in self._alarms.values():
                    if a.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED):
                        alarms_data.append({
                            "alarm_id": a.alarm_id,
                            "equipment_id": a.equipment_id,
                            "message": a.message,
                            "severity": a.severity.value,
                            "state": a.state.value,
                            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
                        })

            snapshot = {
                "equipment": equipment_data,
                "points": points_data,
                "alarms": alarms_data,
                "timestamp": datetime.now().isoformat(),
            }

            conn = await self.db._get_async_connection()
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await conn.execute(
                "DELETE FROM state_snapshots WHERE id NOT IN (SELECT id FROM state_snapshots ORDER BY created_at DESC LIMIT 5)"
            )
            await conn.execute(
                "INSERT INTO state_snapshots (snapshot_json, created_at) VALUES (?, ?)",
                (json.dumps(snapshot), datetime.now().isoformat())
            )
            await conn.commit()
            logger.info(f"State snapshot saved: {len(equipment_data)} equipment, {len(points_data)} points, {len(alarms_data)} alarms")

        except Exception as e:
            logger.error(f"Failed to take state snapshot: {e}")

    async def restore_from_snapshot(self) -> bool:
        """Restore state from most recent database snapshot (warm-start)."""
        if not self.db:
            return False

        try:
            import json
            conn = await self.db._get_async_connection()

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            async with conn.execute(
                "SELECT snapshot_json FROM state_snapshots ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                logger.info("No snapshot found — cold start")
                return False

            snapshot = json.loads(row[0])

            for eq_data in snapshot.get("equipment", []):
                eq = Equipment(
                    equipment_id=eq_data["equipment_id"],
                    name=eq_data["name"],
                    equipment_type=EquipmentType(eq_data["equipment_type"]),
                    status=EquipmentStatus(eq_data["status"]),
                    location=eq_data.get("location", ""),
                    runtime_hours=eq_data.get("runtime_hours", 0),
                    efficiency=eq_data["efficiency"] / 100 if eq_data.get("efficiency") else None,
                    parent_equipment_id=eq_data.get("parent_equipment_id") or None,
                )
                self._equipment[eq.equipment_id] = eq
                if eq.location:
                    self._update_topology(eq)

            for pt_data in snapshot.get("points", []):
                point = BMSDataPoint(
                    point_id=pt_data["point_id"],
                    name=pt_data.get("name", pt_data["point_id"]),
                    equipment_id=pt_data.get("equipment_id", ""),
                    value=pt_data["value"],
                    unit=pt_data.get("unit", ""),
                    timestamp=datetime.fromisoformat(pt_data["timestamp"]) if pt_data.get("timestamp") else datetime.now(),
                )
                self._points[point.point_id] = point
                if point.equipment_id and point.equipment_id in self._equipment:
                    eq = self._equipment[point.equipment_id]
                    if point.point_id not in eq.data_points:
                        eq.data_points.append(point.point_id)

            for al_data in snapshot.get("alarms", []):
                from agent_commercial.bms_data_model import AlarmSeverity
                alarm = Alarm(
                    alarm_id=al_data["alarm_id"],
                    equipment_id=al_data["equipment_id"],
                    message=al_data["message"],
                    severity=AlarmSeverity(al_data["severity"]),
                    state=AlarmState(al_data["state"]),
                )
                if al_data.get("triggered_at"):
                    alarm.triggered_at = datetime.fromisoformat(al_data["triggered_at"])
                self._alarms[alarm.alarm_id] = alarm

            logger.info(
                f"State restored from snapshot: {len(self._equipment)} equipment, "
                f"{len(self._points)} points, {len(self._alarms)} alarms"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to restore from snapshot: {e}")
            return False

    async def get_historical_telemetry(self, equipment_id_or_type: str, days: int = 28) -> Any:
        """
        Queries and reconstructs historical telemetry as a pivoted pandas DataFrame.
        """
        import pandas as pd
        if not self.db:
            return pd.DataFrame()
            
        # 1. Resolve equipment IDs
        equipment_ids = []
        async with self._lock:
            for eq_id, eq in self._equipment.items():
                if (eq_id == equipment_id_or_type or 
                        (eq.equipment_type and eq.equipment_type.value.lower() == equipment_id_or_type.lower()) or 
                        (eq.equipment_type and eq.equipment_type.name.lower() == equipment_id_or_type.lower())):
                    equipment_ids.append(eq_id)
        
        if not equipment_ids:
            # Maybe equipment_id_or_type is just equipment_id directly
            equipment_ids = [equipment_id_or_type]

        # 2. Get sim time
        conn = await self.db._get_async_connection()
        sim_now = datetime.now()
        try:
            async with conn.execute("SELECT MAX(timestamp) FROM data_points") as c:
                row = await c.fetchone()
                if row and row[0]:
                    val_str = str(row[0])
                    if "T" in val_str:
                        sim_now = datetime.fromisoformat(val_str.split(".")[0].split("+")[0])
                    else:
                        sim_now = datetime.fromisoformat(val_str)
        except Exception:
            pass
            
        cutoff = (sim_now - timedelta(days=days)).isoformat()
        
        # 3. Retrieve points in bulk
        placeholders = ",".join(["?"] * len(equipment_ids))
        query = f"""
            SELECT point_id, value, timestamp 
            FROM data_points 
            WHERE equipment_id IN ({placeholders}) AND timestamp > ?
            ORDER BY timestamp ASC
        """
        params = tuple(equipment_ids) + (cutoff,)
        
        rows = []
        async with conn.execute(query, params) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]
            
        if not rows:
            logger.warning(f"No historical telemetry found for {equipment_id_or_type} in last {days} days")
            return pd.DataFrame()
            
        # 4. Pivot in Python for maximum control over column mappings
        records = defaultdict(dict)
        suffix_map = {
            "CHWST": "evap_lwt",
            "CHWRT": "evap_ewt",
            "CWS": "cond_ewt",
            "CWR": "cond_lwt",
            "KW": "power_kw",
            "LOAD": "capacity_tons",
            "SAT": "sat",
            "RAT": "rat",
            "MAT": "mat",
            "OAT": "oat",
            "SAF": "sa_flow",
            "RAF": "ra_flow",
            "CLG_VLV": "cooling_valve",
            "HTG_VLV": "heating_valve",
            "OA_DMPR": "oa_damper",
            "FLT_DP": "filter_dp",
            "FAN_SPD": "fan_speed",
        }
        
        for r in rows:
            ts = r["timestamp"]
            pt_id = r["point_id"]
            val = r["value"]
            
            # Extract suffix
            suffix = pt_id.split("/")[-1] if "/" in pt_id else pt_id
            
            # Add directly
            records[ts][suffix] = val
            records[ts][suffix.lower()] = val
            
            # Add mapped
            if suffix in suffix_map:
                records[ts][suffix_map[suffix]] = val
                
        # Build pandas DataFrame
        df_data = []
        for ts, pts in records.items():
            pts["timestamp"] = ts
            df_data.append(pts)
            
        df = pd.DataFrame(df_data)
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp").reset_index(drop=True)
            
        logger.info(f"Pivoted historical telemetry: {len(df)} rows, columns: {list(df.columns)}")
        return df

