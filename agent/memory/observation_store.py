"""
Observation Store - SQLite-backed time-decay memory
Medium-term behavioral observations and patterns.
"""

import os
import sqlite3
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class ObservationStore:
    """
    Time-decay observation storage using SQLite.
    
    Features:
    - Automatic time-based decay
    - Structured queries
    - Importance weighting
    - Automatic cleanup
    
    Example:
        store = ObservationStore("./data/memories")
        store.add("User typically leaves home at 8:30 AM on weekdays",
                  category="routine", importance=0.8)
        
        recent = store.get_recent(hours=24)
    """
    
    def __init__(self, persist_dir: str = "./data/memories", 
                 decay_days: int = 30):
        self.persist_dir = persist_dir
        self.decay_days = decay_days
        self.db_path = os.path.join(persist_dir, "observations.db")
        
        os.makedirs(persist_dir, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    importance REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_category 
                ON observations(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created 
                ON observations(created_at DESC)
            """)
            conn.commit()
        logger.info(f"[ObservationStore] SQLite initialized at {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def add(self, content: str, category: str = "general",
            importance: float = 0.5, ttl_hours: Optional[int] = None,
            metadata: Optional[Dict] = None) -> str:
        """
        Add an observation.
        
        Args:
            content: The observation text
            category: Category (routine, behavior, anomaly, etc.)
            importance: How important (0-1), affects decay
            ttl_hours: Custom TTL, or use default decay
            metadata: Additional data
            
        Returns:
            Observation ID
        """
        obs_id = f"obs_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        # Calculate expiry based on importance
        if ttl_hours:
            expires = datetime.now() + timedelta(hours=ttl_hours)
        else:
            # Higher importance = longer retention
            adjusted_days = self.decay_days * (0.5 + importance)
            expires = datetime.now() + timedelta(days=adjusted_days)
        
        meta_json = json.dumps(metadata) if metadata else None
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO observations 
                (id, content, category, importance, expires_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (obs_id, content, category, importance, expires, meta_json))
            conn.commit()
        
        logger.debug(f"[ObservationStore] Added: {content[:50]}...")
        return obs_id
    
    def get_recent(self, hours: int = 24, category: Optional[str] = None,
                   limit: int = 20) -> List[Dict]:
        """
        Get recent observations.
        
        Args:
            hours: How far back to look
            category: Filter by category
            limit: Max results
            
        Returns:
            List of observations with time-weighted scores
        """
        since = datetime.now() - timedelta(hours=hours)
        
        query = """
            SELECT * FROM observations 
            WHERE created_at > ? AND (expires_at IS NULL OR expires_at > ?)
        """
        params = [since, datetime.now()]
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        
        observations = []
        now = datetime.now()
        for row in rows:
            # Calculate time-weighted score
            created = datetime.fromisoformat(row['created_at'])
            age_hours = (now - created).total_seconds() / 3600
            time_weight = max(0.1, 1 - (age_hours / (hours * 2)))
            
            observations.append({
                "id": row['id'],
                "content": row['content'],
                "category": row['category'],
                "importance": row['importance'],
                "created_at": row['created_at'],
                "score": time_weight * row['importance'],
                "metadata": json.loads(row['metadata']) if row['metadata'] else {}
            })
        
        return sorted(observations, key=lambda x: x['score'], reverse=True)
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Simple keyword search in observations."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM observations 
                WHERE content LIKE ? 
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
            """, (f"%{query}%", datetime.now(), limit)).fetchall()
        
        return [self._row_to_dict(row) for row in rows]
    
    def _row_to_dict(self, row) -> Dict:
        """Convert sqlite row to dict."""
        return {
            "id": row['id'],
            "content": row['content'],
            "category": row['category'],
            "importance": row['importance'],
            "created_at": row['created_at'],
            "metadata": json.loads(row['metadata']) if row['metadata'] else {}
        }
    
    def delete(self, obs_id: str) -> bool:
        """Delete an observation."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_expired(self) -> int:
        """Remove expired observations. Call periodically."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM observations WHERE expires_at < ?",
                (datetime.now(),)
            )
            conn.commit()
            deleted = cursor.rowcount
        
        if deleted > 0:
            logger.info(f"[ObservationStore] Cleaned up {deleted} expired observations")
        return deleted
    
    def get_by_category(self, category: str, limit: int = 20) -> List[Dict]:
        """Get all observations in a category."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM observations 
                WHERE category = ? AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
            """, (category, datetime.now(), limit)).fetchall()
        
        return [self._row_to_dict(row) for row in rows]
    
    def list_categories(self) -> List[str]:
        """List all observation categories."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT category FROM observations"
            ).fetchall()
        return [row['category'] for row in rows]
    
    def export_all(self) -> Dict:
        """Export all observations (GDPR Article 20)."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM observations").fetchall()
        
        return {
            "type": "observations",
            "count": len(rows),
            "data": [self._row_to_dict(row) for row in rows],
            "exported_at": datetime.now().isoformat()
        }
    
    def clear_all(self) -> bool:
        """Delete all observations (GDPR Article 17)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM observations")
            conn.commit()
        logger.info("[ObservationStore] All observations cleared")
        return True
