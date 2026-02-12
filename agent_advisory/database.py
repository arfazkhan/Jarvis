"""
Database Manager for Advisory System
=====================================

Manages SQLite database for recommendations and trust metrics.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

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
        self._init_database()
        logger.info(f"Advisory database initialized at {db_path}")
    
    def _init_database(self):
        """Create tables if they don't exist"""
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Recommendations table
            cursor.execute("""
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
            cursor.execute("""
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
            cursor.execute("""
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
            cursor.execute("""
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
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_econ_query 
                ON economy_trajectories(query)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rec_status 
                ON recommendations(status)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rec_operator 
                ON recommendations(operator_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rec_building 
                ON recommendations(building_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_operator 
                ON operator_preferences(operator_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_context 
                ON operator_preferences(context_type)
            """)
            
            conn.commit()
            logger.info("Database schema initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        try:
            yield conn
        finally:
            conn.close()
    
    def execute(self, query: str, params: tuple = ()):
        """Execute a single query"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
    
    def fetch_one(self, query: str, params: tuple = ()):
        """Fetch single row"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def fetch_all(self, query: str, params: tuple = ()):
        """Fetch all rows"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_stats(self):
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM recommendations")
            rec_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM trust_metrics")
            metrics_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM operator_preferences")
            pref_count = cursor.fetchone()["count"]
            
            return {
                "recommendations": rec_count,
                "trust_metrics": metrics_count,
                "preferences": pref_count,
                "db_path": self.db_path
            }
