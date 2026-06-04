"""
Building Belief Store - SQLite-backed persistent latent situational understanding.
Maintains stateful, cumulative building beliefs and hypotheses across swarm turns.
"""

import os
import sqlite3
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class BuildingBeliefStore:
    """
    Stateful storage for persistent building beliefs and active diagnostic hypotheses.
    
    Provides:
    - Persistent SQLite storage for building belief state
    - Evolving confidence scores with Bayesian/exponential reinforcement
    - Temporal decay for outdated or non-recurring hypotheses
    - Direct integration with Queen Coordinator context injection
    """
    
    def __init__(self, persist_dir: str = "./data/memories"):
        self.persist_dir = persist_dir
        # Ensure path redirect if isolated verify runs set ARVIS_MEMORY_DIR
        env_mem_dir = os.environ.get("ARVIS_MEMORY_DIR")
        if env_mem_dir:
            self.persist_dir = env_mem_dir
            
        self.db_path = os.path.join(self.persist_dir, "conversations.db") # Re-use existing SQLite DB or observations.db
        # But let's isolate beliefs cleanly into observations.db or a dedicated beliefs.db to prevent lockups.
        # Standardizing on observations.db since it's already structured for medium-term memory.
        self.db_path = os.path.join(self.persist_dir, "observations.db")
        
        os.makedirs(self.persist_dir, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database with the beliefs schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS building_beliefs (
                    belief_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    supporting_signals TEXT DEFAULT '[]',
                    verification_status TEXT DEFAULT 'PENDING_INSPECTION',
                    operator_trust_high INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_belief_target 
                ON building_beliefs(target_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_belief_confidence 
                ON building_beliefs(confidence DESC)
            """)
            conn.commit()
        logger.info(f"[BuildingBeliefStore] SQLite beliefs schema initialized at {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with WAL mode enabled."""
        from agent_commercial.database import get_sync_db
        conn = get_sync_db(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
            
    def add_or_update_belief(
        self,
        target_id: str,
        hypothesis: str,
        confidence: float,
        supporting_signals: Optional[List[str]] = None,
        verification_status: str = "PENDING_INSPECTION",
        operator_trust_high: int = 1,
        metadata: Optional[Dict] = None,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Add or reinforce a building belief/hypothesis.
        
        If a belief already exists for this target and hypothesis, confidence is updated
        using a Bayesian-inspired temporal reinforcement model.
        """
        now = timestamp or datetime.now()
        signals = supporting_signals or []
        meta_json = json.dumps(metadata) if metadata else None
        signals_json = json.dumps(signals)
        
        with self._get_connection() as conn:
            # Check if a matching hypothesis already exists for the target
            cursor = conn.execute("""
                SELECT belief_id, confidence, supporting_signals 
                FROM building_beliefs 
                WHERE target_id = ? AND hypothesis = ?
            """, (target_id, hypothesis))
            existing = cursor.fetchone()
            
            if existing:
                belief_id = existing['belief_id']
                old_conf = existing['confidence']
                # Merge supporting signals without duplicates
                old_signals = json.loads(existing['supporting_signals']) if existing['supporting_signals'] else []
                merged_signals = list(set(old_signals + signals))
                merged_signals_json = json.dumps(merged_signals)

                # Refractory guard: duplicate/concurrent swarm passes for the SAME
                # query re-record the same belief within seconds. Reinforcing on
                # those inflates confidence with no new evidence (observed: one
                # query drove a belief 0.85→0.95 across 4 duplicate passes). Only
                # reinforce if the last update is older than the refractory window;
                # otherwise just merge signals and keep the stronger confidence.
                _REFRACTORY_S = 90
                _recent = False
                try:
                    _prev = conn.execute(
                        "SELECT updated_at FROM building_beliefs WHERE belief_id = ?",
                        (belief_id,)
                    ).fetchone()
                    if _prev and _prev['updated_at']:
                        _age = (now - datetime.fromisoformat(_prev['updated_at'])).total_seconds()
                        _recent = _age < _REFRACTORY_S
                except Exception:
                    _recent = False

                if _recent:
                    # Same-burst re-record: do NOT compound confidence.
                    final_conf = max(old_conf, confidence)
                else:
                    # Reinforce confidence dynamically: c_new = c_old + beta * (1 - c_old)
                    beta = 0.15  # Reinforcement scale factor
                    reinforced_conf = min(1.0, old_conf + beta * (1.0 - old_conf))
                    # Overwrite confidence if the incoming confidence is explicitly higher
                    final_conf = max(reinforced_conf, confidence)
                
                conn.execute("""
                    UPDATE building_beliefs 
                    SET confidence = ?, supporting_signals = ?, updated_at = ?, verification_status = ?, metadata = ?
                    WHERE belief_id = ?
                """, (final_conf, merged_signals_json, now.isoformat(), verification_status, meta_json, belief_id))
                conn.commit()
                logger.info(f"[BuildingBeliefStore] Reinforced belief {belief_id} on {target_id}: confidence {final_conf:.2f}")
            else:
                # Add new belief
                belief_id = f"belief_{now.strftime('%Y%m%d%H%M%S%f')}"
                conn.execute("""
                    INSERT INTO building_beliefs 
                    (belief_id, target_id, hypothesis, confidence, supporting_signals, verification_status, operator_trust_high, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (belief_id, target_id, hypothesis, confidence, signals_json, verification_status, operator_trust_high, now.isoformat(), now.isoformat(), meta_json))
                conn.commit()
                logger.info(f"[BuildingBeliefStore] Logged new belief {belief_id} on {target_id}: confidence {confidence:.2f}")
                
        return belief_id
        
    def apply_time_decay(self, decay_rate: float = 0.05, threshold: float = 0.15) -> int:
        """
        Apply temporal decay to non-confirmed beliefs.
        If confidence drops below threshold, the belief is pruned.
        """
        with self._get_connection() as conn:
            # Query all beliefs that are not confirmed/resolved
            cursor = conn.execute("""
                SELECT belief_id, confidence, target_id 
                FROM building_beliefs 
                WHERE verification_status != 'CONFIRMED' AND verification_status != 'RESOLVED'
            """)
            beliefs = cursor.fetchall()
            
            decayed = 0
            pruned = 0
            for belief in beliefs:
                b_id = belief['belief_id']
                old_conf = belief['confidence']
                new_conf = old_conf * (1.0 - decay_rate)
                
                if new_conf < threshold:
                    conn.execute("DELETE FROM building_beliefs WHERE belief_id = ?", (b_id,))
                    pruned += 1
                else:
                    conn.execute("UPDATE building_beliefs SET confidence = ? WHERE belief_id = ?", (new_conf, b_id))
                    decayed += 1
                    
            conn.commit()
            
        if pruned > 0 or decayed > 0:
            logger.info(f"[BuildingBeliefStore] Decay cycle: decayed {decayed} beliefs, pruned {pruned} stale beliefs.")
            
        return pruned
        
    def list_active_beliefs(self) -> List[Dict]:
        """List all active building beliefs, sorted by confidence."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM building_beliefs 
                WHERE verification_status != 'RESOLVED'
                ORDER BY confidence DESC
            """).fetchall()
            
        return [self._row_to_dict(row) for row in rows]
        
    def get_by_target(self, target_id: str) -> List[Dict]:
        """Get all active beliefs associated with a specific equipment target."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM building_beliefs 
                WHERE target_id = ? AND verification_status != 'RESOLVED'
                ORDER BY confidence DESC
            """, (target_id,)).fetchall()
            
        return [self._row_to_dict(row) for row in rows]
        
    def resolve_belief(self, belief_id: str) -> bool:
        """Mark a belief as resolved (cleared)."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE building_beliefs 
                SET verification_status = 'RESOLVED', confidence = 0.0, updated_at = ?
                WHERE belief_id = ?
            """, (datetime.now().isoformat(), belief_id))
            conn.commit()
            return cursor.rowcount > 0
            
    def resolve_by_target(self, target_id: str) -> bool:
        """Mark all beliefs for a specific target equipment as resolved."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE building_beliefs 
                SET verification_status = 'RESOLVED', confidence = 0.0, updated_at = ?
                WHERE target_id = ? AND verification_status != 'RESOLVED'
            """, (datetime.now().isoformat(), target_id))
            conn.commit()
            return cursor.rowcount > 0
            
    def resolve_by_target_prefix(self, target_prefix: str) -> bool:
        """
        Mark all beliefs whose target_id starts with target_prefix as resolved.
        
        Useful when the operator query contains a short-form equipment ID (e.g. 'AHU-07')
        but beliefs were stored under a longer canonical ID (e.g. 'AHU-07-CONSISTENCY').
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE building_beliefs 
                SET verification_status = 'RESOLVED', confidence = 0.0, updated_at = ?
                WHERE target_id LIKE ? AND verification_status != 'RESOLVED'
            """, (datetime.now().isoformat(), f"{target_prefix}%"))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"[BuildingBeliefStore] Resolved {cursor.rowcount} belief(s) via prefix '{target_prefix}%'")
            return cursor.rowcount > 0

            
    def _row_to_dict(self, row) -> Dict:
        """Convert SQLite database row into standard Python dictionary."""
        return {
            "belief_id": row['belief_id'],
            "target_id": row['target_id'],
            "hypothesis": row['hypothesis'],
            "confidence": row['confidence'],
            "supporting_signals": json.loads(row['supporting_signals']) if row['supporting_signals'] else [],
            "verification_status": row['verification_status'],
            "operator_trust_high": bool(row['operator_trust_high']),
            "created_at": row['created_at'],
            "updated_at": row['updated_at'],
            "metadata": json.loads(row['metadata']) if row['metadata'] else {}
        }
        
    def clear_all(self) -> bool:
        """Delete all beliefs from store."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM building_beliefs")
            conn.commit()
        logger.info("[BuildingBeliefStore] All beliefs cleared.")
        return True
