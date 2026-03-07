"""
Database Manager for Advisory System
=====================================

Manages SQLite database for recommendations and trust metrics.
"""

import sqlite3
import aiosqlite
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger("arvis.advisory.database")


class AdvisoryDatabase:
    """Database manager for advisory system"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file. If None, uses default.
        """
        if db_path is None:
            # Default: agent_bms/data/advisory.db
            base_path = Path(__file__).parent.parent / "agent_bms" / "data"
            base_path.mkdir(parents=True, exist_ok=True)
            db_path = str(base_path / "advisory.db")
        
        self.db_path = db_path
        self._async_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        
        # We can't await in __init__, so we'll ensure init'd on first connection
        self._initialized = False
        
        logger.info(f"Advisory database initialized at {db_path}")
    
    async def _ensure_initialized(self):
        """Ensure database schema is created"""
        if self._initialized:
            return
            
        async with self._lock:
            # Re-check after acquiring lock
            if not self._initialized:
                await self._init_database()
                self._initialized = True

    async def _init_database(self):
        """Create tables if they don't exist (Async)"""
        
        # Use a local connection to avoid recursive lock in get_async_connection
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            
            # Recommendations table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    context TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    calibrated_confidence REAL,
                    reasoning TEXT,
                    predicted_outcome TEXT,
                    status TEXT DEFAULT 'pending',
                    human_action TEXT,
                    decision_time REAL,
                    operator_id TEXT,
                    actual_outcome TEXT,
                    outcome_quality TEXT DEFAULT 'unknown',
                    outcome_measured_at REAL,
                    building_id TEXT,
                    equipment_ids TEXT,
                    tags TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Trust metrics table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_metrics (
                    date TEXT PRIMARY KEY,
                    total_recommendations INTEGER,
                    adoption_rate REAL,
                    acceptance_count INTEGER,
                    rejection_count INTEGER,
                    modification_count INTEGER,
                    accuracy_when_followed REAL,
                    excellent_outcomes INTEGER,
                    good_outcomes INTEGER,
                    acceptable_outcomes INTEGER,
                    poor_outcomes INTEGER,
                    calibration_error REAL,
                    calibration_buckets TEXT,
                    regret_rate REAL,
                    false_alarm_rate REAL,
                    computed_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Operator preferences table (SQLite fallback for ChromaDB)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS operator_preferences (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    operator_id TEXT NOT NULL,
                    context_type TEXT NOT NULL,
                    context_features TEXT,
                    agent_recommendation TEXT,
                    operator_choice TEXT,
                    is_agreement INTEGER,
                    preference_signal TEXT,
                    confidence REAL,
                    outcome_quality TEXT,
                    building_id TEXT,
                    equipment_ids TEXT
                )
            """)
            
            # Tool Economy Trajectories table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS economy_trajectories (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    query TEXT NOT NULL,
                    site_type TEXT,
                    tool_chain TEXT NOT NULL,
                    utility_score REAL NOT NULL,
                    success INTEGER DEFAULT 1,
                    data_density INTEGER,
                    latency_ms REAL
                )
            """)
            
            # Create indices for performance
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_econ_query ON economy_trajectories(query)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_operator ON recommendations(operator_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_building ON recommendations(building_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_operator ON operator_preferences(operator_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_context ON operator_preferences(context_type)")
            
            await conn.commit()
            logger.info("Advisory database schema initialized successfully")
    
    @asynccontextmanager
    async def get_async_connection(self):
        """Context manager for a short-lived per-operation database connection.
        
        Uses WAL mode for concurrent reads/writes instead of a mutex lock.
        Each operation opens, uses, and closes its own connection to prevent
        lock contention between the simulation write loop and API read requests.
        """
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA busy_timeout=5000")  # 5 second timeout instead of hang
            yield conn
        finally:
            await conn.close()

    async def execute(self, query: str, params: tuple = ()):
        """Execute a single query (Async)"""
        await self._ensure_initialized()
        async with self.get_async_connection() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.lastrowid
    
    async def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch single row (Async)"""
        await self._ensure_initialized()
        async with self.get_async_connection() as conn:
            async with conn.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows (Async)"""
        await self._ensure_initialized()
        async with self.get_async_connection() as conn:
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_stats(self):
        """Get database statistics (Async)"""
        await self._ensure_initialized()
        async with self.get_async_connection() as conn:
            async with conn.execute("SELECT COUNT(*) as count FROM recommendations") as cursor:
                row = await cursor.fetchone()
                rec_count = row["count"]
            
            async with conn.execute("SELECT COUNT(*) as count FROM trust_metrics") as cursor:
                row = await cursor.fetchone()
                metrics_count = row["count"]
            
            async with conn.execute("SELECT COUNT(*) as count FROM operator_preferences") as cursor:
                row = await cursor.fetchone()
                pref_count = row["count"]
            
            return {
                "recommendations": rec_count,
                "trust_metrics": metrics_count,
                "preferences": pref_count,
                "db_path": self.db_path
            }

    async def close(self):
        """Close database connections (Async) - no-op in per-connection model"""
        # WAL mode allows multiple concurrent connections, no shared conn to close
        if self._async_conn:
            try:
                await self._async_conn.close()
            except Exception:
                pass
            self._async_conn = None
