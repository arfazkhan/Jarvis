"""
Conversation Buffer - In-memory with SQLite backup
Short-term dialogue memory with summary compression.
"""

import os
import sqlite3
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class ConversationBuffer:
    """
    Sliding window conversation memory with persistence.
    
    Features:
    - 10-turn sliding window (configurable)
    - Automatic summary compression for overflow
    - SQLite backup for restart recovery
    - Session management
    
    Example:
        buffer = ConversationBuffer("./data/memories")
        buffer.add("user", "turn on the lights")
        buffer.add("assistant", "Lights on.")
        
        context = buffer.get_context()  # Returns formatted history
    """
    
    def __init__(self, persist_dir: str = "./data/memories",
                 max_turns: int = 10, session_timeout_minutes: int = 30):
        self.persist_dir = persist_dir
        self.max_turns = max_turns
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.db_path = os.path.join(persist_dir, "conversations.db")
        
        # In-memory current session
        self._history: deque = deque(maxlen=max_turns * 2)  # *2 for user+assistant pairs
        self._summary: Optional[str] = None
        self._session_id: Optional[str] = None
        self._last_activity: datetime = datetime.now()
        
        os.makedirs(persist_dir, exist_ok=True)
        self._init_db()
        self._restore_session()
    
    def _get_connection(self):
        """Get database connection using centralized get_sync_db factory."""
        from agent_commercial.database import get_sync_db
        return get_sync_db(self.db_path)
    
    def _init_db(self):
        """Initialize SQLite for session persistence."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP,
                    summary TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_messages 
                ON messages(session_id, timestamp)
            """)
            conn.commit()
        logger.info(f"[ConversationBuffer] SQLite initialized at {self.db_path}")
    
    def _restore_session(self):
        """Restore the most recent active session on startup."""
        with self._get_connection() as conn:
            # Find most recent session within timeout
            cutoff = datetime.now() - self.session_timeout
            row = conn.execute("""
                SELECT * FROM sessions 
                WHERE last_activity > ?
                ORDER BY last_activity DESC LIMIT 1
            """, (cutoff,)).fetchone()
            
            if row:
                self._session_id = row['id']
                self._summary = row['summary']
                
                # Restore messages
                messages = conn.execute("""
                    SELECT role, content FROM messages 
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (self._session_id, self.max_turns * 2)).fetchall()
                
                # Reverse to get chronological order
                for msg in reversed(messages):
                    self._history.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })
                
                logger.info(f"[ConversationBuffer] Restored session {self._session_id} "
                           f"with {len(self._history)} messages")
    
    def _ensure_session(self):
        """Ensure we have an active session."""
        now = datetime.now()
        
        # Check if session expired
        if self._session_id and (now - self._last_activity) > self.session_timeout:
            self._start_new_session()
        elif not self._session_id:
            self._start_new_session()
        
        self._last_activity = now
    
    def _start_new_session(self):
        """Start a new conversation session."""
        self._session_id = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._history.clear()
        self._summary = None
        
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO sessions (id, last_activity) VALUES (?, ?)",
                (self._session_id, datetime.now())
            )
            conn.commit()
        
        logger.info(f"[ConversationBuffer] Started new session: {self._session_id}")
    
    def add(self, role: str, content: str):
        """
        Add a message to the conversation.
        
        Args:
            role: "user" or "assistant"
            content: Message content
        """
        self._ensure_session()
        
        message = {"role": role, "content": content}
        
        # Check if we need to compress
        if len(self._history) >= self.max_turns * 2:
            self._compress_oldest()
        
        self._history.append(message)
        
        # Persist to SQLite
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (self._session_id, role, content)
            )
            conn.execute(
                "UPDATE sessions SET last_activity = ? WHERE id = ?",
                (datetime.now(), self._session_id)
            )
            conn.commit()
    
    def _compress_oldest(self):
        """Compress oldest messages into summary."""
        if len(self._history) < 6:
            return
        
        # Take oldest 4 messages
        oldest = []
        for _ in range(4):
            if self._history:
                oldest.append(self._history.popleft())
        
        # Create simple summary
        topics = []
        for msg in oldest:
            if msg['role'] == 'user':
                # Extract key topics (simple approach)
                words = msg['content'].lower().split()
                keywords = [w for w in words if len(w) > 3 and w not in 
                           ['turn', 'the', 'what', 'please', 'could', 'would']]
                topics.extend(keywords[:2])
        
        if topics:
            new_summary = f"Earlier discussed: {', '.join(set(topics))}"
            if self._summary:
                self._summary = f"{self._summary}. {new_summary}"
            else:
                self._summary = new_summary
        
        # Persist summary
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE id = ?",
                (self._summary, self._session_id)
            )
            conn.commit()
        
        logger.debug(f"[ConversationBuffer] Compressed, summary: {self._summary}")
    
    def get_context(self) -> List[Dict]:
        """
        Get conversation context for LLM.
        
        Returns:
            List of messages including summary if present
        """
        context = []
        
        # Add summary as system context if present
        if self._summary:
            context.append({
                "role": "system",
                "content": f"Previous conversation context: {self._summary}"
            })
        
        # Add recent messages
        context.extend(list(self._history))
        
        return context
    
    def get_last_n(self, n: int = 5) -> List[Dict]:
        """Get last N messages only."""
        return list(self._history)[-n:]
    
    def clear_session(self):
        """Clear current session."""
        self._history.clear()
        self._summary = None
        if self._session_id:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", 
                           (self._session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?",
                           (self._session_id,))
                conn.commit()
        self._session_id = None
    
    def get_session_info(self) -> Dict:
        """Get current session info."""
        return {
            "session_id": self._session_id,
            "message_count": len(self._history),
            "has_summary": self._summary is not None,
            "last_activity": self._last_activity.isoformat()
        }
    
    def export_all(self) -> Dict:
        """Export all conversations (GDPR)."""
        with self._get_connection() as conn:
            sessions = conn.execute("SELECT * FROM sessions").fetchall()
            
            data = []
            for session in sessions:
                messages = conn.execute(
                    "SELECT role, content, timestamp FROM messages WHERE session_id = ?",
                    (session['id'],)
                ).fetchall()
                
                data.append({
                    "session_id": session['id'],
                    "created_at": session['created_at'],
                    "summary": session['summary'],
                    "messages": [dict(m) for m in messages]
                })
        
        return {
            "type": "conversations",
            "count": len(data),
            "data": data,
            "exported_at": datetime.now().isoformat()
        }
    
    def clear_all(self) -> bool:
        """Delete all conversations (GDPR)."""
        self._history.clear()
        self._summary = None
        self._session_id = None
        
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()
        
        logger.info("[ConversationBuffer] All conversations cleared")
        return True
