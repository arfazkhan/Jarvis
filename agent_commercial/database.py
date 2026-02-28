"""
Database Layer for ARVIS Ops Copilot
=====================================

SQLite persistence for BMS state, alarms, and energy readings.
Uses SQLAlchemy with async support for non-blocking I/O.

This ensures data survives restarts and enables historical analysis.
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Use aiosqlite for non-blocking I/O
import sqlite3
import aiosqlite
import json
import asyncio

logger = logging.getLogger("arvis.bms.database")

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent / "data" / "arvis_bms.db"


class BMSDatabase:
    """
    SQLite persistence layer for BMS data.
    
    Stores:
    - Equipment registry
    - Data point history
    - Alarms (active and historical)
    - Energy readings
    - GSAS scores
    
    Usage:
        >>> db = BMSDatabase()
        >>> db.save_data_point("CH-01/CHWST", 7.2, "°C")
        >>> history = db.get_point_history("CH-01/CHWST", hours=24)
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._async_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        
        logger.info(f"BMSDatabase initialized: {self.db_path}")

    async def _get_async_connection(self) -> aiosqlite.Connection:
        """Get or create asynchronous database connection with WAL mode enabled"""
        async with self._lock:
            if self._async_conn is None:
                self._async_conn = await aiosqlite.connect(str(self.db_path))
                self._async_conn.row_factory = aiosqlite.Row
                
                # Enable WAL mode for high concurrency
                try:
                    await self._async_conn.execute("PRAGMA journal_mode=WAL")
                    await self._async_conn.execute("PRAGMA synchronous=NORMAL")
                    await self._async_conn.execute("PRAGMA cache_size=-64000") # 64MB cache
                except Exception as e:
                    logger.warning(f"Failed to enable WAL mode in async: {e}")
                    
            return self._async_conn
            
    
    # ═══════════════════════════════════════════════════════════════════════════
    # EQUIPMENT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_equipment(self, equipment: Dict[str, Any]) -> None:
        """Save or update equipment (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO equipment 
            (equipment_id, name, equipment_type, status, location, runtime_hours, 
             efficiency, last_maintenance, parent_equipment_id, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            equipment.get("equipment_id"),
            equipment.get("name"),
            equipment.get("equipment_type"),
            equipment.get("status", "unknown"),
            equipment.get("location"),
            equipment.get("runtime_hours", 0),
            equipment.get("efficiency"),
            equipment.get("last_maintenance"),
            equipment.get("parent_equipment_id"),
            json.dumps(equipment.get("metadata", {})),
            datetime.now().isoformat(),
        ))
        
        await conn.commit()
    
    async def get_equipment(self, equipment_id: str) -> Optional[Dict]:
        """Get equipment by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM equipment WHERE equipment_id = ?", (equipment_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Convert aiosqlite.Row to dict
                return dict(row)
        return None
    
    async def get_all_equipment(self) -> List[Dict]:
        """Get all equipment (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM equipment ORDER BY equipment_id") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATA POINT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_data_point(
        self, 
        point_id: str, 
        value: float, 
        unit: str = "",
        equipment_id: str = None,
        quality: str = "good",
        timestamp: datetime = None
    ) -> None:
        """Save a data point reading (Async)"""
        conn = await self._get_async_connection()
        
        ts = (timestamp or datetime.now()).isoformat()
        
        await conn.execute("""
            INSERT INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (point_id, equipment_id, value, unit, quality, ts))
        
        await conn.commit()
    
    async def save_data_points_batch(self, points: List[Dict]) -> None:
        """Save multiple data points efficiently (Async)"""
        conn = await self._get_async_connection()
        
        data = [
            (
                p.get("point_id"),
                p.get("equipment_id"),
                p.get("value"),
                p.get("unit", ""),
                p.get("quality", "good"),
                (p.get("timestamp") or datetime.now()).isoformat() if isinstance(p.get("timestamp"), datetime) else p.get("timestamp", datetime.now().isoformat())
            )
            for p in points
        ]
        
        await conn.executemany("""
            INSERT INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, data)
        
        await conn.commit()
    
    async def get_point_history(
        self, 
        point_id: str, 
        hours: int = 24,
        limit: int = 1000
    ) -> List[Dict]:
        """Get historical values for a point (Async)"""
        conn = await self._get_async_connection()
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        async with conn.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (point_id, cutoff, limit)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
    
    async def get_latest_value(self, point_id: str) -> Optional[Dict]:
        """Get the most recent value for a point (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (point_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def get_latest_values_batch(self, point_ids: List[str]) -> Dict[str, float]:
        """Get latest values for multiple points (Async)"""
        result = {}
        for point_id in point_ids:
            latest = await self.get_latest_value(point_id)
            if latest:
                result[point_id] = latest["value"]
        return result
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALARM OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_alarm(self, alarm: Dict[str, Any]) -> None:
        """Save or update an alarm (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO alarms 
            (alarm_id, equipment_id, source_point_id, message, severity, state,
             triggered_at, acknowledged_at, acknowledged_by, resolved_at, cluster_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            alarm.get("alarm_id"),
            alarm.get("equipment_id"),
            alarm.get("source_point_id"),
            alarm.get("message"),
            alarm.get("severity"),
            alarm.get("state", "active"),
            alarm.get("triggered_at", datetime.now().isoformat()),
            alarm.get("acknowledged_at"),
            alarm.get("acknowledged_by"),
            alarm.get("resolved_at"),
            alarm.get("cluster_id"),
            json.dumps(alarm.get("metadata", {})),
        ))
        
        await conn.commit()
    
    async def get_active_alarms(self) -> List[Dict]:
        """Get all active alarms (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT * FROM alarms 
            WHERE state IN ('active', 'acknowledged')
            ORDER BY 
                CASE severity 
                    WHEN 'critical' THEN 1 
                    WHEN 'high' THEN 2 
                    WHEN 'medium' THEN 3 
                    WHEN 'low' THEN 4 
                    ELSE 5 
                END,
                triggered_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_alarm_count_by_severity(self) -> Dict[str, int]:
        """Get count of active alarms by severity (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT severity, COUNT(*) as count 
            FROM alarms 
            WHERE state IN ('active', 'acknowledged')
            GROUP BY severity
        """) as cursor:
            rows = await cursor.fetchall()
            return {row["severity"]: row["count"] for row in rows}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENERGY OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_energy_reading(
        self,
        meter_id: str,
        value: float,
        unit: str = "kW",
        outdoor_temp: float = None,
        occupancy: float = None,
        timestamp: datetime = None
    ) -> None:
        """Save energy meter reading (Async)"""
        conn = await self._get_async_connection()
        
        ts = (timestamp or datetime.now()).isoformat()
        
        await conn.execute("""
            INSERT INTO energy_readings (meter_id, value, unit, outdoor_temp, occupancy, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (meter_id, value, unit, outdoor_temp, occupancy, ts))
        
        await conn.commit()
    
    async def get_energy_today(self, meter_id: str = None) -> float:
        """Get total energy consumption for today (kWh) (Async)"""
        conn = await self._get_async_connection()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        
        if meter_id:
            query = """
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE meter_id = ? AND timestamp > ?
            """
            params = (meter_id, today_start)
        else:
            query = """
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE timestamp > ?
            """
            params = (today_start,)
            
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row and row["avg_kw"]:
                # Estimate kWh: avg_kw * hours since midnight
                hours = (datetime.now() - datetime.now().replace(hour=0, minute=0, second=0)).seconds / 3600
                return row["avg_kw"] * hours
        return 0.0
    
    async def get_energy_baseline_comparison(self, meter_id: str = None) -> float:
        """Compare today's energy to 7-day baseline (Async)"""
        conn = await self._get_async_connection()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        # Get today's average
        if meter_id:
            today_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE meter_id = ? AND timestamp > ?"
            today_params = (meter_id, today_start)
        else:
            today_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE timestamp > ?"
            today_params = (today_start,)
            
        async with conn.execute(today_query, today_params) as cursor:
            today_row = await cursor.fetchone()
            today_avg = today_row["avg_kw"] if today_row and today_row["avg_kw"] else 0
        
        # Get baseline average
        if meter_id:
            base_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE meter_id = ? AND timestamp > ? AND timestamp < ?"
            base_params = (meter_id, week_ago, today_start)
        else:
            base_query = "SELECT AVG(value) as avg_kw FROM energy_readings WHERE timestamp > ? AND timestamp < ?"
            base_params = (week_ago, today_start)
            
        async with conn.execute(base_query, base_params) as cursor:
            baseline_row = await cursor.fetchone()
            baseline_avg = baseline_row["avg_kw"] if baseline_row and baseline_row["avg_kw"] else 0
        
        if baseline_avg > 0:
            return ((today_avg - baseline_avg) / baseline_avg) * 100
        return 0.0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ZONE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_zone(self, zone: Dict[str, Any]) -> None:
        """Save or update zone configuration (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO zones 
            (zone_id, name, floor, building, co2_point_id, vav_point_id, 
             lighting_point_id, return_air_point_id, schedule_id, load_kw, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            zone.get("zone_id"),
            zone.get("name"),
            zone.get("floor"),
            zone.get("building"),
            zone.get("co2_point_id"),
            zone.get("vav_point_id"),
            zone.get("lighting_point_id"),
            zone.get("return_air_point_id"),
            zone.get("schedule_id"),
            zone.get("load_kw", 2.0),
            json.dumps(zone.get("metadata", {})),
        ))
        
        await conn.commit()
    
    async def get_all_zones(self) -> List[Dict]:
        """Get all zone configurations (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM zones ORDER BY building, floor, name") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_zone_with_current_values(self, zone_id: str) -> Optional[Dict]:
        """Get zone config with current sensor values (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM zones WHERE zone_id = ?", (zone_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            
            zone = dict(row)
            
            # Get current sensor values
            if zone.get("co2_point_id"):
                latest = await self.get_latest_value(zone["co2_point_id"])
                zone["co2_ppm"] = latest["value"] if latest else None
            
            if zone.get("vav_point_id"):
                latest = await self.get_latest_value(zone["vav_point_id"])
                zone["vav_damper_pct"] = latest["value"] if latest else None
            
            if zone.get("lighting_point_id"):
                latest = await self.get_latest_value(zone["lighting_point_id"])
                zone["light_status"] = latest["value"] > 0 if latest else None
            
            return zone
    
    # ═══════════════════════════════════════════════════════════════════════════
    # WORK ORDER OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def create_work_order(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str,
        pre_snapshot: Dict[str, float]
    ) -> None:
        """Create a work order with pre-maintenance snapshot (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT INTO work_orders (work_order_id, equipment_id, task_type, status, pre_snapshot, opened_at)
            VALUES (?, ?, ?, 'open', ?, ?)
        """, (
            work_order_id,
            equipment_id,
            task_type,
            json.dumps(pre_snapshot),
            datetime.now().isoformat(),
        ))
        
        await conn.commit()
    
    async def close_work_order(
        self,
        work_order_id: str,
        post_snapshot: Dict[str, float],
        verification_result: Dict[str, Any]
    ) -> None:
        """Close work order with post-maintenance data (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            UPDATE work_orders 
            SET status = 'closed', 
                post_snapshot = ?, 
                closed_at = ?,
                verification_result = ?
            WHERE work_order_id = ?
        """, (
            json.dumps(post_snapshot),
            datetime.now().isoformat(),
            json.dumps(verification_result),
            work_order_id,
        ))
        
        await conn.commit()
    
    async def get_work_order(self, work_order_id: str) -> Optional[Dict]:
        """Get work order details (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                wo = dict(row)
                wo["pre_snapshot"] = json.loads(wo.get("pre_snapshot") or "{}")
                wo["post_snapshot"] = json.loads(wo.get("post_snapshot") or "{}")
                wo["verification_result"] = json.loads(wo.get("verification_result") or "{}")
                return wo
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GSAS OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def save_gsas_score(
        self,
        building_id: str,
        overall_score: float,
        certification_level: str,
        category_scores: Dict[str, float]
    ) -> None:
        """Save GSAS assessment score (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT INTO gsas_scores (building_id, overall_score, certification_level, category_scores, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            building_id,
            overall_score,
            certification_level,
            json.dumps(category_scores),
            datetime.now().isoformat(),
        ))
        
        await conn.commit()
    
    async def get_latest_gsas_score(self, building_id: str = None) -> Optional[Dict]:
        """Get the most recent GSAS score (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM gsas_scores 
                WHERE building_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """
            params = (building_id,)
        else:
            query = """
                SELECT * FROM gsas_scores 
                ORDER BY timestamp DESC LIMIT 1
            """
            params = ()
        
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                result["category_scores"] = json.loads(result.get("category_scores") or "{}")
                return result
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAINTENANCE ANALYTICS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def get_equipment_requiring_maintenance(self, days: int = 7) -> List[Dict]:
        """Get equipment with high failure probability or overdue maintenance (Async)"""
        conn = await self._get_async_connection()
        
        overdue_cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        
        async with conn.execute("""
            SELECT * FROM equipment 
            WHERE last_maintenance < ? OR last_maintenance IS NULL
            ORDER BY last_maintenance ASC
        """, (overdue_cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_pending_insights_count(self) -> int:
        """Get count of unacknowledged high-priority alarms (as insights) (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute("""
            SELECT COUNT(*) as count FROM alarms 
            WHERE state = 'active' AND severity IN ('critical', 'high')
        """) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def cleanup_old_data(self, days: int = 30) -> int:
        """Remove data older than specified days (Async)"""
        conn = await self._get_async_connection()
        
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        await conn.execute("DELETE FROM data_points WHERE timestamp < ?", (cutoff,))
        await conn.execute("DELETE FROM energy_readings WHERE timestamp < ?", (cutoff,))
        await conn.execute("DELETE FROM alarms WHERE resolved_at < ? AND state = 'resolved'", (cutoff,))
        
        await conn.commit()
        
        # Note: rowcount might not be readily available on the connection after commit in aiosqlite,
        # but we usually don't depend on it for logic.
        return 0 
    
    async def save_audit_log(
        self,
        user: str,
        method: str,
        path: str,
        status: int,
        ip: str = "unknown",
        latency_ms: float = 0.0
    ) -> None:
        """Save a security audit record (Async)"""
        conn = await self._get_async_connection()
        ts = time.time()
        
        await conn.execute("""
            INSERT INTO audit_logs (timestamp, method, path, status, user, ip, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ts, method, path, status, user, ip, latency_ms))
        
        await conn.commit()
    
    async def close(self):
        """Close database connections (Async)"""
        async with self._lock:
            if self._async_conn:
                await self._async_conn.close()
                self._async_conn = None


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_db_instance: Optional[BMSDatabase] = None


def get_database(db_path: str = None) -> BMSDatabase:
    """Get or create the singleton database instance"""
    global _db_instance
    
    if _db_instance is None:
        _db_instance = BMSDatabase(db_path)
    
    return _db_instance
