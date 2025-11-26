"""
Preference Store
----------------
Persistent storage for learned user preferences.
Stores (category, key, value, confidence) tuples.
"""

import sqlite3
import json
import time
from typing import Dict, Any, List, Optional, Tuple

class PreferenceStore:
    def __init__(self, db_path: str = "preferences.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                category TEXT,
                key TEXT,
                value TEXT, -- JSON encoded value
                confidence REAL,
                last_updated REAL,
                PRIMARY KEY (category, key)
            )
        """)
        conn.commit()
        conn.close()

    def get(self, category: str, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a preference"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value, confidence FROM preferences WHERE category=? AND key=?", (category, key))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "value": json.loads(row[0]),
                "confidence": row[1]
            }
        return None

    def get_all_by_category(self, category: str) -> Dict[str, Any]:
        """Retrieve all preferences in a category"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, confidence FROM preferences WHERE category=?", (category,))
        rows = cursor.fetchall()
        conn.close()
        
        result = {}
        for row in rows:
            result[row[0]] = {
                "value": json.loads(row[1]),
                "confidence": row[2]
            }
        return result

    def set(self, category: str, key: str, value: Any, confidence: float):
        """Set or update a preference"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO preferences (category, key, value, confidence, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (category, key, json.dumps(value), confidence, time.time()))
        conn.commit()
        conn.close()

    def delete_all(self):
        """Clear all preferences (for testing)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM preferences")
        conn.commit()
        conn.close()

    def decay_confidence(self, factor: float = 0.997):
        """Decay confidence of all preferences"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE preferences SET confidence = confidence * ?", (factor,))
        conn.commit()
        conn.close()
