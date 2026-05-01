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
                logger.info(f"Establishing NEW async connection to: {self.db_path}")
                self._async_conn = await aiosqlite.connect(str(self.db_path))
                self._async_conn.row_factory = aiosqlite.Row
                
                # Enable WAL mode for high concurrency
                try:
                    await self._async_conn.execute("PRAGMA journal_mode=WAL")
                    await self._async_conn.execute("PRAGMA synchronous=NORMAL")
                    await self._async_conn.execute("PRAGMA cache_size=-64000") # 64MB cache
                    
                    # Ensure schema exists (Automatic Initialization)
                    await self._init_schema(self._async_conn)
                    
                except Exception as e:
                    logger.error(f"❌ Failed to initialize database in async: {e}")
                    # If init fails, reset connection so next call tries again
                    try:
                        await self._async_conn.close()
                    except:
                        pass
                    self._async_conn = None
                    raise e # Propagate error
                    
            return self._async_conn

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        """Initialize database tables if they don't exist"""
        logger.info("🛠️ Verifying database schema...")
        # Get list of existing tables
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            rows = await cursor.fetchall()
            existing_tables = [row[0] for row in rows]
            logger.info(f"Existing tables: {existing_tables}")

        # 1. Equipment table
        if 'equipment' not in existing_tables:
            logger.info("Creating table: equipment")
            await conn.execute("""
            CREATE TABLE equipment (
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
                updated_at TEXT
            )
            """)
        
        # 2. Data Points table
        if 'data_points' not in existing_tables:
            logger.info("Creating table: data_points")
            await conn.execute("""
            CREATE TABLE data_points (
                point_id TEXT,
                equipment_id TEXT,
                value REAL,
                unit TEXT,
                quality TEXT DEFAULT 'good',
                timestamp TEXT,
                PRIMARY KEY (point_id, timestamp)
            )
            """)
        
        # 3. Alarms table
        if 'alarms' not in existing_tables:
            logger.info("Creating table: alarms")
            await conn.execute("""
            CREATE TABLE alarms (
                alarm_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                source_point_id TEXT,
                message TEXT,
                severity TEXT,
                state TEXT DEFAULT 'active',
                triggered_at TEXT,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                resolved_at TEXT,
                cluster_id TEXT,
                metadata TEXT
            )
            """)
        
        # 4. Energy Readings table
        if 'energy_readings' not in existing_tables:
            logger.info("Creating table: energy_readings")
            await conn.execute("""
            CREATE TABLE energy_readings (
                meter_id TEXT,
                value REAL,
                unit TEXT DEFAULT 'kW',
                outdoor_temp REAL,
                occupancy REAL,
                timestamp TEXT,
                PRIMARY KEY (meter_id, timestamp)
            )
            """)
        
        # 5. Zones table
        if 'zones' not in existing_tables:
            logger.info("Creating table: zones")
            await conn.execute("""
            CREATE TABLE zones (
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
        
        # 6. Work Orders table
        if 'work_orders' not in existing_tables:
            logger.info("Creating table: work_orders")
            await conn.execute("""
            CREATE TABLE work_orders (
                work_order_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                task_type TEXT,
                status TEXT DEFAULT 'open',
                pre_snapshot TEXT,
                post_snapshot TEXT,
                opened_at TEXT,
                closed_at TEXT,
                verification_result TEXT
            )
            """)
        
        # 7. GSAS Scores table
        if 'gsas_scores' not in existing_tables:
            logger.info("Creating table: gsas_scores")
            await conn.execute("""
            CREATE TABLE gsas_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id TEXT,
                overall_score REAL,
                certification_level TEXT,
                category_scores TEXT,
                timestamp TEXT
            )
            """)
        
        # 8. Audit Logs table
        if 'audit_logs' not in existing_tables:
            logger.info("Creating table: audit_logs")
            await conn.execute("""
            CREATE TABLE audit_logs (
                timestamp REAL,
                method TEXT,
                path TEXT,
                status INTEGER,
                user TEXT,
                ip TEXT,
                latency_ms REAL
            )
            """)

        # 9. Fleet Metrics
        if 'fleet_metrics' not in existing_tables:
            logger.info("Creating table: fleet_metrics")
            await conn.execute("""
            CREATE TABLE fleet_metrics (
                building_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                timestamp TEXT,
                PRIMARY KEY (building_id, metric_name)
            )
            """)

        # 10. Fleet Insights
        if 'fleet_insights' not in existing_tables:
            logger.info("Creating table: fleet_insights")
            await conn.execute("""
            CREATE TABLE fleet_insights (
                insight_id TEXT PRIMARY KEY,
                building_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL,
                status TEXT DEFAULT 'active',
                timestamp TEXT
            )
            """)

        # 11. Chat Sessions
        if 'chat_sessions' not in existing_tables:
            logger.info("Creating table: chat_sessions")
            await conn.execute("""
            CREATE TABLE chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)

        # 12. Chat Messages
        if 'chat_messages' not in existing_tables:
            logger.info("Creating table: chat_messages")
            await conn.execute("""
            CREATE TABLE chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT,
                FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
            )
            """)
            
            # Create indexes for fast message lookup by session
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages(session_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_sess_updated ON chat_sessions(updated_at DESC)")

        # 13. Operator Feedback (Learning Signal)
        if 'operator_feedback' not in existing_tables:
            logger.info("Creating table: operator_feedback")
            await conn.execute("""
            CREATE TABLE operator_feedback (
                feedback_id TEXT PRIMARY KEY,
                session_id TEXT,
                equipment_id TEXT,
                recommendation_id TEXT,
                feedback_type TEXT,
                rating INTEGER,
                comment TEXT,
                timestamp TEXT,
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_equipment ON operator_feedback(equipment_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON operator_feedback(timestamp DESC)")

        # 14. Trust Metrics
        if 'trust_metrics' not in existing_tables:
            logger.info("Creating table: trust_metrics")
            await conn.execute("""
            CREATE TABLE trust_metrics (
                metric_id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                building_id TEXT,
                follow_through_rate REAL DEFAULT 0.0,
                avg_response_time_seconds REAL,
                total_recommendations INTEGER DEFAULT 0,
                accepted_recommendations INTEGER DEFAULT 0,
                rejected_recommendations INTEGER DEFAULT 0,
                silence_rate REAL DEFAULT 0.0,
                last_updated TEXT,
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trust_operator ON trust_metrics(operator_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trust_building ON trust_metrics(building_id)")

        # 15. Recommendations
        if 'recommendations' not in existing_tables:
            logger.info("Creating table: recommendations")
            await conn.execute("""
            CREATE TABLE recommendations (
                recommendation_id TEXT PRIMARY KEY,
                equipment_id TEXT,
                domain TEXT,
                recommendation_type TEXT,
                priority TEXT,
                title TEXT,
                description TEXT,
                confidence REAL,
                evidence TEXT,
                action TEXT,
                created_at TEXT,
                accepted_at TEXT,
                rejected_at TEXT,
                operator_id TEXT,
                status TEXT DEFAULT 'pending',
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_equipment ON recommendations(equipment_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_created ON recommendations(created_at DESC)")

        # 16. Briefings
        if 'briefings' not in existing_tables:
            logger.info("Creating table: briefings")
            await conn.execute("""
            CREATE TABLE briefings (
                briefing_id TEXT PRIMARY KEY,
                period TEXT,
                building_id TEXT,
                title TEXT,
                critical_items TEXT,
                attention_items TEXT,
                info_items TEXT,
                wins_items TEXT,
                generated_at TEXT,
                operator_id TEXT,
                operator_response TEXT,
                responded_at TEXT,
                status TEXT DEFAULT 'pending',
                metadata TEXT
            )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_building ON briefings(building_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_period ON briefings(period)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_brief_generated ON briefings(generated_at DESC)")

        
        await conn.commit()
        logger.info("✅ Database schema verification complete.")
            
    
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

    async def get_fleet_insights(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the latest insights generated across the fleet"""
        query = "SELECT * FROM fleet_insights ORDER BY timestamp DESC LIMIT ?"
        rows = await self.fetch_all(query, (limit,))
        return rows
        
    # ═══════════════════════════════════════════════════════════════════════════
    # CHAT HISTORY COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def create_chat_session(self, session_id: str, title: str = "New Conversation") -> Optional[str]:
        """Create a new chat session."""
        now = datetime.now().isoformat()
        conn = await self._get_async_connection()
        query = "INSERT INTO chat_sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)"
        try:
            await conn.execute(query, (session_id, title, now, now))
            await conn.commit()
            return session_id
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            return None
            
    async def update_chat_session_timestamp(self, session_id: str) -> None:
        """Update the last activity timestamp for a chat session."""
        now = datetime.now().isoformat()
        conn = await self._get_async_connection()
        try:
            await conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
            await conn.commit()
        except Exception as e:
            logger.error(f"Failed to update chat session timestamp: {e}")

    async def add_chat_message(self, session_id: str, message_id: str, role: str, content: str) -> bool:
        """Add a message to a specific chat session."""
        now = datetime.now().isoformat()
        conn = await self._get_async_connection()
        query = "INSERT INTO chat_messages (message_id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)"
        try:
            await conn.execute(query, (message_id, session_id, role, content, now))
            await conn.commit()
            await self.update_chat_session_timestamp(session_id)
            return True
        except Exception as e:
            logger.error(f"Failed to add chat message: {e}")
            return False

    async def get_chat_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve a list of recent chat sessions."""
        conn = await self._get_async_connection()
        query = "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?"
        async with conn.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_chat_history(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve messages for a specific session ordered by timestamp."""
        conn = await self._get_async_connection()
        query = "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?"
        async with conn.execute(query, (session_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
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
    # ALARM STATE OPERATIONS (for bms_state_engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def update_alarm_state(
        self,
        alarm_id: str,
        state: str = None,
        acknowledged_by: str = None,
        acknowledged_at: datetime = None,
        resolved_at: datetime = None
    ) -> None:
        """Update alarm state fields (Async)"""
        conn = await self._get_async_connection()
        
        fields = []
        params = []
        if state is not None:
            fields.append("state = ?")
            params.append(state.value if hasattr(state, 'value') else state)
        if acknowledged_by is not None:
            fields.append("acknowledged_by = ?")
            params.append(acknowledged_by)
        if acknowledged_at is not None:
            fields.append("acknowledged_at = ?")
            params.append(acknowledged_at.isoformat() if hasattr(acknowledged_at, 'isoformat') else acknowledged_at)
        if resolved_at is not None:
            fields.append("resolved_at = ?")
            params.append(resolved_at.isoformat() if hasattr(resolved_at, 'isoformat') else resolved_at)
        
        if not fields:
            return
        
        params.append(alarm_id)
        query = f"UPDATE alarms SET {', '.join(fields)} WHERE alarm_id = ?"
        await conn.execute(query, params)
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # OPERATOR FEEDBACK (for trust calibration + learning)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_operator_feedback(self, feedback: Dict[str, Any]) -> None:
        """Save operator feedback on a recommendation (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO operator_feedback 
            (feedback_id, session_id, equipment_id, recommendation_id, feedback_type, 
             rating, comment, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.get("feedback_id"),
            feedback.get("session_id"),
            feedback.get("equipment_id"),
            feedback.get("recommendation_id"),
            feedback.get("feedback_type"),
            feedback.get("rating"),
            feedback.get("comment"),
            datetime.now().isoformat(),
            json.dumps(feedback.get("metadata", {})),
        ))
        await conn.commit()

    async def get_operator_feedback(
        self,
        equipment_id: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get operator feedback history (Async)"""
        conn = await self._get_async_connection()
        
        if equipment_id:
            query = """
                SELECT * FROM operator_feedback 
                WHERE equipment_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """
            params = (equipment_id, limit)
        else:
            query = "SELECT * FROM operator_feedback ORDER BY timestamp DESC LIMIT ?"
            params = (limit,)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ═══════════════════════════════════════════════════════════════════════════
    # TRUST METRICS (for trust calibrator)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_trust_metrics(self, metrics: Dict[str, Any]) -> None:
        """Save or update trust metrics for an operator (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO trust_metrics 
            (metric_id, operator_id, building_id, follow_through_rate, avg_response_time_seconds,
             total_recommendations, accepted_recommendations, rejected_recommendations, 
             silence_rate, last_updated, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.get("metric_id"),
            metrics.get("operator_id"),
            metrics.get("building_id"),
            metrics.get("follow_through_rate", 0.0),
            metrics.get("avg_response_time_seconds"),
            metrics.get("total_recommendations", 0),
            metrics.get("accepted_recommendations", 0),
            metrics.get("rejected_recommendations", 0),
            metrics.get("silence_rate", 0.0),
            datetime.now().isoformat(),
            json.dumps(metrics.get("metadata", {})),
        ))
        await conn.commit()

    async def get_trust_metrics(
        self,
        operator_id: str,
        building_id: str = None
    ) -> Optional[Dict]:
        """Get trust metrics for an operator (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM trust_metrics 
                WHERE operator_id = ? AND building_id = ?
                LIMIT 1
            """
            params = (operator_id, building_id)
        else:
            query = """
                SELECT * FROM trust_metrics 
                WHERE operator_id = ?
                ORDER BY last_updated DESC LIMIT 1
            """
            params = (operator_id,)
        
        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_trust_after_feedback(
        self,
        operator_id: str,
        recommendation_id: str,
        accepted: bool,
        response_time_seconds: float = None
    ) -> None:
        """Increment trust counters after feedback (Async)"""
        conn = await self._get_async_connection()
        
        # Get existing
        existing = await self.get_trust_metrics(operator_id)
        
        total = (existing.get("total_recommendations", 0) or 0) + 1
        accepted_count = (existing.get("accepted_recommendations", 0) or 0) + (1 if accepted else 0)
        rejected_count = (existing.get("rejected_recommendations", 0) or 0) + (0 if accepted else 1)
        follow_rate = accepted_count / total if total > 0 else 0.0
        
        # Update avg response time
        avg_rt = existing.get("avg_response_time_seconds") or 0
        if response_time_seconds is not None:
            prev_count = total - 1
            if prev_count > 0:
                avg_rt = (avg_rt * prev_count + response_time_seconds) / total
            else:
                avg_rt = response_time_seconds
        
        await conn.execute("""
            UPDATE trust_metrics SET
                total_recommendations = ?,
                accepted_recommendations = ?,
                rejected_recommendations = ?,
                follow_through_rate = ?,
                avg_response_time_seconds = ?,
                last_updated = ?
            WHERE operator_id = ?
        """, (
            total, accepted_count, rejected_count, follow_rate, avg_rt,
            datetime.now().isoformat(), operator_id
        ))
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # RECOMMENDATIONS (for advisory engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_recommendation(self, rec: Dict[str, Any]) -> None:
        """Save an AI recommendation (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO recommendations 
            (recommendation_id, equipment_id, domain, recommendation_type, priority,
             title, description, confidence, evidence, action, created_at, 
             accepted_at, rejected_at, operator_id, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.get("recommendation_id"),
            rec.get("equipment_id"),
            rec.get("domain"),
            rec.get("recommendation_type"),
            rec.get("priority", "medium"),
            rec.get("title"),
            rec.get("description"),
            rec.get("confidence", 0.5),
            json.dumps(rec.get("evidence", [])),
            rec.get("action"),
            datetime.now().isoformat(),
            rec.get("accepted_at"),
            rec.get("rejected_at"),
            rec.get("operator_id"),
            rec.get("status", "pending"),
            json.dumps(rec.get("metadata", {})),
        ))
        await conn.commit()

    async def get_recommendation(self, recommendation_id: str) -> Optional[Dict]:
        """Get a recommendation by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?",
            (recommendation_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                result["evidence"] = json.loads(result.get("evidence") or "[]")
                return result
        return None

    async def get_recommendations_by_equipment(
        self,
        equipment_id: str,
        status: str = None,
        limit: int = 20
    ) -> List[Dict]:
        """Get recommendations for an equipment (Async)"""
        conn = await self._get_async_connection()
        
        if status:
            query = """
                SELECT * FROM recommendations 
                WHERE equipment_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
            """
            params = (equipment_id, status, limit)
        else:
            query = """
                SELECT * FROM recommendations 
                WHERE equipment_id = ?
                ORDER BY created_at DESC LIMIT ?
            """
            params = (equipment_id, limit)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                r = dict(row)
                r["evidence"] = json.loads(r.get("evidence") or "[]")
                result.append(r)
            return result

    async def update_recommendation_status(
        self,
        recommendation_id: str,
        status: str,
        operator_id: str = None,
        accepted_at: datetime = None,
        rejected_at: datetime = None
    ) -> None:
        """Update recommendation status (accepted/rejected/pending) (Async)"""
        conn = await self._get_async_connection()
        
        now = datetime.now().isoformat()
        
        if status == "accepted":
            await conn.execute("""
                UPDATE recommendations SET 
                    status = 'accepted', 
                    operator_id = ?,
                    accepted_at = ?
                WHERE recommendation_id = ?
            """, (operator_id, now, recommendation_id))
        elif status == "rejected":
            await conn.execute("""
                UPDATE recommendations SET 
                    status = 'rejected', 
                    operator_id = ?,
                    rejected_at = ?
                WHERE recommendation_id = ?
            """, (operator_id, now, recommendation_id))
        else:
            await conn.execute("""
                UPDATE recommendations SET status = ? WHERE recommendation_id = ?
            """, (status, recommendation_id))
        
        await conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # BRIEFINGS (for briefing engine)
    # ═══════════════════════════════════════════════════════════════════════════

    async def save_briefing(self, briefing: Dict[str, Any]) -> None:
        """Save a generated briefing (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            INSERT OR REPLACE INTO briefings 
            (briefing_id, period, building_id, title, critical_items, attention_items,
             info_items, wins_items, generated_at, operator_id, operator_response,
             responded_at, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            briefing.get("briefing_id"),
            briefing.get("period"),
            briefing.get("building_id"),
            briefing.get("title"),
            json.dumps(briefing.get("critical_items", [])),
            json.dumps(briefing.get("attention_items", [])),
            json.dumps(briefing.get("info_items", [])),
            json.dumps(briefing.get("wins_items", [])),
            datetime.now().isoformat(),
            briefing.get("operator_id"),
            briefing.get("operator_response"),
            briefing.get("responded_at"),
            briefing.get("status", "pending"),
            json.dumps(briefing.get("metadata", {})),
        ))
        await conn.commit()

    async def get_briefing(self, briefing_id: str) -> Optional[Dict]:
        """Get a briefing by ID (Async)"""
        conn = await self._get_async_connection()
        
        async with conn.execute(
            "SELECT * FROM briefings WHERE briefing_id = ?",
            (briefing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                for key in ["critical_items", "attention_items", "info_items", "wins_items"]:
                    result[key] = json.loads(result.get(key) or "[]")
                return result
        return None

    async def get_briefings_by_period(
        self,
        period: str,
        building_id: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """Get briefings by period (Async)"""
        conn = await self._get_async_connection()
        
        if building_id:
            query = """
                SELECT * FROM briefings 
                WHERE period = ? AND building_id = ?
                ORDER BY generated_at DESC LIMIT ?
            """
            params = (period, building_id, limit)
        else:
            query = """
                SELECT * FROM briefings 
                WHERE period = ?
                ORDER BY generated_at DESC LIMIT ?
            """
            params = (period, limit)
        
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                r = dict(row)
                for key in ["critical_items", "attention_items", "info_items", "wins_items"]:
                    r[key] = json.loads(r.get(key) or "[]")
                result.append(r)
            return result

    async def update_briefing_response(
        self,
        briefing_id: str,
        operator_response: str,
        status: str = "responded"
    ) -> None:
        """Record operator response to a briefing (Async)"""
        conn = await self._get_async_connection()
        
        await conn.execute("""
            UPDATE briefings SET 
                operator_response = ?,
                responded_at = ?,
                status = ?
            WHERE briefing_id = ?
        """, (
            operator_response,
            datetime.now().isoformat(),
            status,
            briefing_id,
        ))
        await conn.commit()


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
