"""
Memory Manager
--------------
Handles persistent storage of events, summaries, and user data.
Implements retention policies and GDPR-compliant export/delete.
"""

import json
import sqlite3
import time
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from config.settings import get_config

# Load configuration
CONFIG = get_config("cognitive")
MEMORY_CONFIG = CONFIG.get("memory", {})

DB_PATH = Path(MEMORY_CONFIG.get("storage_path", "data/memory/events.db"))
RETENTION_DAYS_RAW = MEMORY_CONFIG.get("retention_days_raw", 90)
RETENTION_DAYS_SUMMARIES = MEMORY_CONFIG.get("retention_days_summaries", 1095)


class MemoryManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Raw events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                event_type TEXT,
                source TEXT,
                payload TEXT,
                embedding_id TEXT
            )
        """)
        
        # Create index on timestamp for fast retrieval and retention cleanup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        
        # Summaries table (for long-term retention)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_str TEXT,
                summary_text TEXT,
                metadata TEXT
            )
        """)
        
        conn.commit()
        conn.close()

    def add_event(self, event: Dict[str, Any]) -> int:
        """
        Store a new event.
        Returns the row ID of the inserted event.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        payload_str = json.dumps(event.get("payload", {}))
        
        cursor.execute("""
            INSERT INTO events (timestamp, event_type, source, payload, embedding_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            event.get("timestamp", time.time()),
            event.get("type", "unknown"),
            event.get("source", "system"),
            payload_str,
            event.get("embedding_id", None)
        ))
        
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

    def get_recent_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve most recent events"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM events"
        params = []
        
        if event_type:
            query += " WHERE event_type = ?"
            params.append(event_type)
            
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row) for row in rows]

    def get_events_in_range(self, start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
        """Retrieve events within a time window"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM events 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (start_ts, end_ts))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert DB row to event dictionary"""
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "type": row["event_type"],
            "source": row["source"],
            "payload": json.loads(row["payload"]) if row["payload"] else {},
            "embedding_id": row["embedding_id"]
        }

    def enforce_retention_policy(self):
        """
        Delete raw events older than RETENTION_DAYS_RAW.
        Summaries are kept longer.
        """
        cutoff_ts = time.time() - (RETENTION_DAYS_RAW * 86400)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_ts,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            print(f"[MemoryManager] Cleaned up {deleted_count} old events.")

    def export_user_data(self, user_id: str) -> Dict[str, Any]:
        """
        GDPR Export: Retrieve all data related to a specific user.
        Note: This assumes payload contains 'user_id' or similar identifier.
        For a simple MVP, we might dump everything if single-user.
        """
        # This is a naive implementation scanning payloads. 
        # In production, we'd want indexed user_id columns.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM events")
        rows = cursor.fetchall()
        conn.close()
        
        user_events = []
        for row in rows:
            event = self._row_to_dict(row)
            # Check if user_id is in payload (recursively or flat)
            payload_str = json.dumps(event["payload"])
            if user_id in payload_str:
                user_events.append(event)
                
        return {"user_id": user_id, "events": user_events, "export_date": datetime.now().isoformat()}

    def delete_user_data(self, user_id: str) -> int:
        """
        GDPR Delete: Remove all data related to a specific user.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Naive approach: select all, check payload in python, delete by ID
        # Optimization: Add user_id column to schema in future
        cursor.execute("SELECT id, payload FROM events")
        rows = cursor.fetchall()
        
        ids_to_delete = []
        for row_id, payload_raw in rows:
            if user_id in payload_raw:
                ids_to_delete.append(row_id)
        
        if ids_to_delete:
            placeholders = ','.join('?' * len(ids_to_delete))
            cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids_to_delete)
            
        deleted_count = len(ids_to_delete)
        conn.commit()
        conn.close()
        
        return deleted_count

    def backup(self, backup_path: Path):
        """Create a backup of the database"""
        shutil.copy2(self.db_path, backup_path)
