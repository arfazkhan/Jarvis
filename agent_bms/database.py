"""
Database Layer for ARVIS Ops Copilot
=====================================

SQLite persistence for BMS state, alarms, and energy readings.
Uses SQLAlchemy with async support for non-blocking I/O.

This ensures data survives restarts and enables historical analysis.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Use SQLite with synchronous driver for simplicity
import sqlite3
import json

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
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file (auto-created if missing)
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._conn = None
        self._init_database()
        
        logger.info(f"BMSDatabase initialized: {self.db_path}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def _init_database(self):
        """Create tables if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Equipment table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equipment (
                equipment_id TEXT PRIMARY KEY,
                name TEXT,
                equipment_type TEXT,
                status TEXT DEFAULT 'unknown',
                location TEXT,
                runtime_hours REAL DEFAULT 0,
                efficiency REAL,
                last_maintenance TEXT,
                parent_equipment_id TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Data points table (time-series)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                point_id TEXT NOT NULL,
                equipment_id TEXT,
                value REAL,
                unit TEXT,
                quality TEXT DEFAULT 'good',
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
            )
        """)
        
        # Index for fast time-range queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_datapoints_point_time 
            ON data_points(point_id, timestamp)
        """)
        
        # Alarms table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                alarm_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                source_point_id TEXT,
                message TEXT,
                severity TEXT,
                state TEXT DEFAULT 'active',
                triggered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                resolved_at TEXT,
                cluster_id TEXT,
                metadata TEXT,
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
            )
        """)
        
        # Energy readings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS energy_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meter_id TEXT NOT NULL,
                value REAL,
                unit TEXT DEFAULT 'kW',
                outdoor_temp REAL,
                occupancy REAL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_energy_meter_time 
            ON energy_readings(meter_id, timestamp)
        """)
        
        # GSAS scores table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gsas_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id TEXT,
                overall_score REAL,
                certification_level TEXT,
                category_scores TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Work orders table (for maintenance verification)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_orders (
                work_order_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                task_type TEXT,
                status TEXT DEFAULT 'open',
                pre_snapshot TEXT,
                post_snapshot TEXT,
                opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT,
                verification_result TEXT,
                FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
            )
        """)
        
        # Zone configuration table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                zone_id TEXT PRIMARY KEY,
                name TEXT,
                floor TEXT,
                building TEXT,
                co2_point_id TEXT,
                vav_point_id TEXT,
                lighting_point_id TEXT,
                return_air_point_id TEXT,
                schedule_id TEXT,
                load_kw REAL DEFAULT 2.0,
                metadata TEXT
            )
        """)
        
        conn.commit()
        logger.debug("Database tables initialized")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # EQUIPMENT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_equipment(self, equipment: Dict[str, Any]) -> None:
        """Save or update equipment"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
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
        
        conn.commit()
    
    def get_equipment(self, equipment_id: str) -> Optional[Dict]:
        """Get equipment by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM equipment WHERE equipment_id = ?", (equipment_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def get_all_equipment(self) -> List[Dict]:
        """Get all equipment"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM equipment ORDER BY equipment_id")
        return [dict(row) for row in cursor.fetchall()]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATA POINT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_data_point(
        self, 
        point_id: str, 
        value: float, 
        unit: str = "",
        equipment_id: str = None,
        quality: str = "good",
        timestamp: datetime = None
    ) -> None:
        """Save a data point reading"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        ts = (timestamp or datetime.now()).isoformat()
        
        cursor.execute("""
            INSERT INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (point_id, equipment_id, value, unit, quality, ts))
        
        conn.commit()
    
    def save_data_points_batch(self, points: List[Dict]) -> None:
        """Save multiple data points efficiently"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
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
        
        cursor.executemany("""
            INSERT INTO data_points (point_id, equipment_id, value, unit, quality, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, data)
        
        conn.commit()
    
    def get_point_history(
        self, 
        point_id: str, 
        hours: int = 24,
        limit: int = 1000
    ) -> List[Dict]:
        """Get historical values for a point"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        cursor.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (point_id, cutoff, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_latest_value(self, point_id: str) -> Optional[Dict]:
        """Get the most recent value for a point"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT value, unit, quality, timestamp 
            FROM data_points 
            WHERE point_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (point_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_latest_values_batch(self, point_ids: List[str]) -> Dict[str, float]:
        """Get latest values for multiple points"""
        result = {}
        for point_id in point_ids:
            latest = self.get_latest_value(point_id)
            if latest:
                result[point_id] = latest["value"]
        return result
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALARM OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_alarm(self, alarm: Dict[str, Any]) -> None:
        """Save or update an alarm"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
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
        
        conn.commit()
    
    def get_active_alarms(self) -> List[Dict]:
        """Get all active alarms"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
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
        """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_alarm_count_by_severity(self) -> Dict[str, int]:
        """Get count of active alarms by severity"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT severity, COUNT(*) as count 
            FROM alarms 
            WHERE state IN ('active', 'acknowledged')
            GROUP BY severity
        """)
        
        return {row["severity"]: row["count"] for row in cursor.fetchall()}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENERGY OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_energy_reading(
        self,
        meter_id: str,
        value: float,
        unit: str = "kW",
        outdoor_temp: float = None,
        occupancy: float = None,
        timestamp: datetime = None
    ) -> None:
        """Save energy meter reading"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        ts = (timestamp or datetime.now()).isoformat()
        
        cursor.execute("""
            INSERT INTO energy_readings (meter_id, value, unit, outdoor_temp, occupancy, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (meter_id, value, unit, outdoor_temp, occupancy, ts))
        
        conn.commit()
    
    def get_energy_today(self, meter_id: str = None) -> float:
        """Get total energy consumption for today (kWh)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        
        if meter_id:
            cursor.execute("""
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE meter_id = ? AND timestamp > ?
            """, (meter_id, today_start))
        else:
            cursor.execute("""
                SELECT AVG(value) as avg_kw, COUNT(*) as readings
                FROM energy_readings 
                WHERE timestamp > ?
            """, (today_start,))
        
        row = cursor.fetchone()
        if row and row["avg_kw"]:
            # Estimate kWh: avg_kw * hours since midnight
            hours = (datetime.now() - datetime.now().replace(hour=0, minute=0, second=0)).seconds / 3600
            return row["avg_kw"] * hours
        return 0.0
    
    def get_energy_baseline_comparison(self, meter_id: str = None) -> float:
        """Compare today's energy to 7-day baseline"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        # Get today's average
        if meter_id:
            cursor.execute("""
                SELECT AVG(value) as avg_kw FROM energy_readings 
                WHERE meter_id = ? AND timestamp > ?
            """, (meter_id, today_start))
        else:
            cursor.execute("""
                SELECT AVG(value) as avg_kw FROM energy_readings 
                WHERE timestamp > ?
            """, (today_start,))
        
        today_row = cursor.fetchone()
        today_avg = today_row["avg_kw"] if today_row and today_row["avg_kw"] else 0
        
        # Get baseline average
        if meter_id:
            cursor.execute("""
                SELECT AVG(value) as avg_kw FROM energy_readings 
                WHERE meter_id = ? AND timestamp > ? AND timestamp < ?
            """, (meter_id, week_ago, today_start))
        else:
            cursor.execute("""
                SELECT AVG(value) as avg_kw FROM energy_readings 
                WHERE timestamp > ? AND timestamp < ?
            """, (week_ago, today_start))
        
        baseline_row = cursor.fetchone()
        baseline_avg = baseline_row["avg_kw"] if baseline_row and baseline_row["avg_kw"] else 0
        
        if baseline_avg > 0:
            return ((today_avg - baseline_avg) / baseline_avg) * 100
        return 0.0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ZONE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_zone(self, zone: Dict[str, Any]) -> None:
        """Save or update zone configuration"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
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
        
        conn.commit()
    
    def get_all_zones(self) -> List[Dict]:
        """Get all zone configurations"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM zones ORDER BY building, floor, name")
        return [dict(row) for row in cursor.fetchall()]
    
    def get_zone_with_current_values(self, zone_id: str) -> Optional[Dict]:
        """Get zone config with current sensor values"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM zones WHERE zone_id = ?", (zone_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        zone = dict(row)
        
        # Get current sensor values
        if zone.get("co2_point_id"):
            latest = self.get_latest_value(zone["co2_point_id"])
            zone["co2_ppm"] = latest["value"] if latest else None
        
        if zone.get("vav_point_id"):
            latest = self.get_latest_value(zone["vav_point_id"])
            zone["vav_damper_pct"] = latest["value"] if latest else None
        
        if zone.get("lighting_point_id"):
            latest = self.get_latest_value(zone["lighting_point_id"])
            zone["light_status"] = latest["value"] > 0 if latest else None
        
        return zone
    
    # ═══════════════════════════════════════════════════════════════════════════
    # WORK ORDER OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def create_work_order(
        self,
        work_order_id: str,
        equipment_id: str,
        task_type: str,
        pre_snapshot: Dict[str, float]
    ) -> None:
        """Create a work order with pre-maintenance snapshot"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO work_orders (work_order_id, equipment_id, task_type, status, pre_snapshot, opened_at)
            VALUES (?, ?, ?, 'open', ?, ?)
        """, (
            work_order_id,
            equipment_id,
            task_type,
            json.dumps(pre_snapshot),
            datetime.now().isoformat(),
        ))
        
        conn.commit()
    
    def close_work_order(
        self,
        work_order_id: str,
        post_snapshot: Dict[str, float],
        verification_result: Dict[str, Any]
    ) -> None:
        """Close work order with post-maintenance data"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
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
        
        conn.commit()
    
    def get_work_order(self, work_order_id: str) -> Optional[Dict]:
        """Get work order details"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (work_order_id,))
        row = cursor.fetchone()
        
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
    
    def save_gsas_score(
        self,
        building_id: str,
        overall_score: float,
        certification_level: str,
        category_scores: Dict[str, float]
    ) -> None:
        """Save GSAS assessment score"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO gsas_scores (building_id, overall_score, certification_level, category_scores, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            building_id,
            overall_score,
            certification_level,
            json.dumps(category_scores),
            datetime.now().isoformat(),
        ))
        
        conn.commit()
    
    def get_latest_gsas_score(self, building_id: str = None) -> Optional[Dict]:
        """Get the most recent GSAS score"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if building_id:
            cursor.execute("""
                SELECT * FROM gsas_scores 
                WHERE building_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (building_id,))
        else:
            cursor.execute("""
                SELECT * FROM gsas_scores 
                ORDER BY timestamp DESC LIMIT 1
            """)
        
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result["category_scores"] = json.loads(result.get("category_scores") or "{}")
            return result
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAINTENANCE ANALYTICS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_equipment_requiring_maintenance(self, days: int = 7) -> List[Dict]:
        """Get equipment with high failure probability or overdue maintenance"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        overdue_cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        
        cursor.execute("""
            SELECT * FROM equipment 
            WHERE last_maintenance < ? OR last_maintenance IS NULL
            ORDER BY last_maintenance ASC
        """, (overdue_cutoff,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_pending_insights_count(self) -> int:
        """Get count of unacknowledged high-priority alarms (as insights)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM alarms 
            WHERE state = 'active' AND severity IN ('critical', 'high')
        """)
        
        row = cursor.fetchone()
        return row["count"] if row else 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════════════
    
    def cleanup_old_data(self, days: int = 30) -> int:
        """Remove data older than specified days"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute("DELETE FROM data_points WHERE timestamp < ?", (cutoff,))
        cursor.execute("DELETE FROM energy_readings WHERE timestamp < ?", (cutoff,))
        cursor.execute("DELETE FROM alarms WHERE resolved_at < ? AND state = 'resolved'", (cutoff,))
        
        conn.commit()
        
        deleted = cursor.rowcount
        logger.info(f"Cleaned up {deleted} old records")
        return deleted
    
    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None


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
