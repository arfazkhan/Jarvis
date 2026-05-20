"""
Operator Pattern Store - Dynamic Few-Shot Learning for BMS
============================================================

Stores successful operator interaction patterns and retrieves similar patterns
for few-shot injection into LLM prompts. Implements the "Update" loop from 
the Titans architecture adapted for Building Management Systems.

Patterns tracked:
- Alarm responses (acknowledge, silence, escalate)
- Chat queries → Tool calls (successful interactions)
- Setpoint adjustments (time-based patterns)
- Energy optimization actions

This enables the Ops Copilot to learn from past successful interactions
without requiring model fine-tuning.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import hashlib

logger = logging.getLogger("arvis.bms.learning.patterns")

# Optional ChromaDB dependency
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = False
    logger.warning("[OperatorPatternStore] ChromaDB not available - patterns won't persist")


class OperatorPatternStore:
    """
    Stores successful operator interaction patterns for dynamic few-shot learning.
    
    When an operator action is successful:
    1. Store (query, tool_calls, outcome) in ChromaDB
    2. When similar queries come in, retrieve past patterns
    3. Inject as few-shot examples in prompt
    
    This creates a learning loop without model fine-tuning.
    
    Example:
        >>> store = OperatorPatternStore(persist_dir="data/patterns")
        >>> store.log_success("What's wrong with CH-01?", [{"tool": "get_equipment_status", ...}])
        >>> patterns = store.get_similar_patterns("Check chiller health")
    """
    
    COLLECTION_QUERIES = "operator_queries"
    COLLECTION_ALARMS = "alarm_responses"
    
    def __init__(self, persist_dir: str = None, max_patterns: int = 1000):
        """
        Initialize operator pattern store.
        
        Args:
            persist_dir: Directory for ChromaDB persistence (default: agent_bms/data/patterns)
            max_patterns: Maximum patterns to store per collection (FIFO eviction)
        """
        if persist_dir is None:
            persist_dir = Path(__file__).parent.parent / "data" / "patterns"
        
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.max_patterns = max_patterns
        
        self.client = None
        self.query_collection = None
        self.alarm_collection = None
        
        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        
        logger.info(f"[OperatorPatternStore] Initialized at {self.persist_dir}")
    
    def _init_chromadb(self):
        """Initialize ChromaDB client and collections."""
        try:
            self.client = chromadb.PersistentClient(
                path=str(self.persist_dir / "patterns_db"),
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Collection for operator queries → tool mappings
            self.query_collection = self.client.get_or_create_collection(
                name=self.COLLECTION_QUERIES,
                metadata={"description": "Operator query patterns for few-shot learning"}
            )
            
            # Collection for alarm response patterns
            self.alarm_collection = self.client.get_or_create_collection(
                name=self.COLLECTION_ALARMS,
                metadata={"description": "Alarm response patterns"}
            )
            
            logger.info(
                f"[OperatorPatternStore] ChromaDB ready: "
                f"{self.query_collection.count()} queries, "
                f"{self.alarm_collection.count()} alarm patterns"
            )
        except Exception as e:
            logger.error(f"[OperatorPatternStore] ChromaDB init failed: {e}")
            self.client = None
    
    def _generate_id(self, text: str) -> str:
        """Generate deterministic ID from text."""
        return hashlib.md5(text.lower().strip().encode()).hexdigest()[:12]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # QUERY PATTERNS (Chat interactions)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_query_success(
        self, 
        query: str, 
        tool_calls: List[Dict], 
        response_quality: str = "good"
    ) -> bool:
        """
        Store a successful query → tool_calls pattern.
        
        Args:
            query: Operator's original query
            tool_calls: List of tool calls that were executed
            response_quality: "good", "excellent", or "acceptable"
            
        Returns:
            Success boolean
        """
        if not self.query_collection:
            return False
        
        try:
            query = query.strip()
            if len(query) < 5:
                return False
            
            def _sanitize(val, default=""):
                return val if val is not None else default

            # Create pattern document
            pattern_id = f"q_{self._generate_id(query)}_{datetime.now().strftime('%H%M%S')}"
            
            # Extract tool info
            tool_name = _sanitize(tool_calls[0].get('tool')) if tool_calls else 'unknown'
            equipment_id = ""
            for tc in tool_calls:
                args = tc.get('args', {})
                if 'equipment_id' in args:
                    equipment_id = _sanitize(args['equipment_id'])
                    break
            
            metadata = {
                "tool": tool_name,
                "equipment_id": equipment_id,
                "tool_calls_json": json.dumps(tool_calls),
                "response_quality": _sanitize(response_quality, "good"),
                "timestamp": datetime.now().isoformat(),
            }
            
            self.query_collection.add(
                documents=[query],
                metadatas=[metadata],
                ids=[pattern_id]
            )
            
            self._evict_if_needed(self.query_collection)
            
            logger.debug(f"[Patterns] Logged query: '{query[:30]}...' → {tool_name}")
            return True
            
        except Exception as e:
            logger.error(f"[Patterns] Failed to log query pattern: {e}")
            return False
    
    def get_similar_queries(
        self, 
        query: str, 
        k: int = 3, 
        min_similarity: float = 0.4
    ) -> List[Dict]:
        """
        Retrieve similar successful query patterns for few-shot injection.
        
        Args:
            query: Current operator query
            k: Number of patterns to retrieve
            min_similarity: Minimum similarity threshold (0-1)
            
        Returns:
            List of similar patterns with their tool calls
        """
        if not self.query_collection or self.query_collection.count() == 0:
            return []
        
        try:
            results = self.query_collection.query(
                query_texts=[query],
                n_results=k
            )
            
            patterns = []
            if results and results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
                    distance = results['distances'][0][i] if results.get('distances') else 1.0
                    
                    # Convert distance to similarity (lower distance = more similar)
                    similarity = max(0, 1 - (distance / 2))
                    
                    if similarity >= min_similarity:
                        patterns.append({
                            "query": doc,
                            "tool": metadata.get('tool', 'unknown'),
                            "equipment_id": metadata.get('equipment_id', ''),
                            "tool_calls": json.loads(metadata.get('tool_calls_json', '[]')),
                            "similarity": round(similarity, 3),
                            "quality": metadata.get('response_quality', 'unknown'),
                        })
            
            # Sort by similarity (highest first)
            patterns.sort(key=lambda x: x['similarity'], reverse=True)
            
            return patterns
            
        except Exception as e:
            logger.error(f"[Patterns] Failed to retrieve query patterns: {e}")
            return []
    
    def format_query_fewshot(self, patterns: List[Dict]) -> str:
        """
        Format retrieved query patterns as few-shot examples for prompt injection.
        
        Args:
            patterns: List of pattern dicts from get_similar_queries
            
        Returns:
            Formatted string for prompt insertion
        """
        if not patterns:
            return ""
        
        lines = ["## Learned patterns from past successful interactions:"]
        
        for p in patterns[:3]:  # Max 3 examples
            lines.append(f"\nOperator: \"{p['query']}\"")
            lines.append(f"Tool used: {p['tool']}")
            if p.get('equipment_id'):
                lines.append(f"Equipment: {p['equipment_id']}")
        
        return "\n".join(lines)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ALARM RESPONSE PATTERNS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_alarm_response(
        self,
        alarm_id: str,
        alarm_type: str,
        equipment_id: str,
        action: str,  # "acknowledged", "silenced", "escalated", "ignored"
        response_time_seconds: float,
        resolved: bool = False
    ) -> bool:
        """
        Store an alarm response pattern.
        
        Args:
            alarm_id: Unique alarm identifier
            alarm_type: Type/message of alarm
            equipment_id: Equipment that triggered alarm
            action: What the operator did
            response_time_seconds: How long to respond
            resolved: Whether the alarm was actually resolved
            
        Returns:
            Success boolean
        """
        if not self.alarm_collection:
            return False
        
        try:
            pattern_id = f"a_{self._generate_id(alarm_id)}_{datetime.now().strftime('%H%M%S')}"
            
            def _sanitize(val, default=""):
                return val if val is not None else default

            # Combine alarm type and equipment for similarity matching
            doc_text = f"{_sanitize(alarm_type)} on {_sanitize(equipment_id)}"
            
            metadata = {
                "alarm_id": _sanitize(alarm_id),
                "alarm_type": _sanitize(alarm_type),
                "equipment_id": _sanitize(equipment_id),
                "action": _sanitize(action),
                "response_time_seconds": response_time_seconds if response_time_seconds is not None else 0.0,
                "resolved": bool(resolved) if resolved is not None else False,
                "timestamp": datetime.now().isoformat(),
            }
            
            self.alarm_collection.add(
                documents=[doc_text],
                metadatas=[metadata],
                ids=[pattern_id]
            )
            
            self._evict_if_needed(self.alarm_collection)
            
            logger.debug(f"[Patterns] Logged alarm response: {alarm_type} → {action}")
            return True
            
        except Exception as e:
            logger.error(f"[Patterns] Failed to log alarm pattern: {e}")
            return False
    
    def get_alarm_patterns(self, alarm_type: str, equipment_id: str = None) -> Dict:
        """
        Get historical response patterns for similar alarms.
        
        Args:
            alarm_type: Type of alarm to analyze
            equipment_id: Optional equipment filter
            
        Returns:
            Summary of how operators typically respond to this alarm type
        """
        if not self.alarm_collection or self.alarm_collection.count() == 0:
            return {"patterns": [], "typical_action": None}
        
        try:
            query = f"{alarm_type} on {equipment_id}" if equipment_id else alarm_type
            
            results = self.alarm_collection.query(
                query_texts=[query],
                n_results=min(20, self.alarm_collection.count())
            )
            
            if not results or not results.get('metadatas'):
                return {"patterns": [], "typical_action": None}
            
            # Analyze response patterns
            action_counts = {}
            total_response_time = 0
            resolved_count = 0
            patterns = []
            
            for metadata in results['metadatas'][0]:
                action = metadata.get('action', 'unknown')
                action_counts[action] = action_counts.get(action, 0) + 1
                total_response_time += metadata.get('response_time_seconds', 0)
                if metadata.get('resolved'):
                    resolved_count += 1
                patterns.append(metadata)
            
            n = len(patterns)
            typical_action = max(action_counts.items(), key=lambda x: x[1])[0] if action_counts else None
            
            return {
                "patterns": patterns[:5],  # Last 5 patterns
                "typical_action": typical_action,
                "action_distribution": action_counts,
                "avg_response_time_seconds": total_response_time / n if n > 0 else 0,
                "resolution_rate": resolved_count / n if n > 0 else 0,
                "sample_size": n,
            }
            
        except Exception as e:
            logger.error(f"[Patterns] Failed to get alarm patterns: {e}")
            return {"patterns": [], "typical_action": None}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _evict_if_needed(self, collection):
        """Remove oldest patterns if over limit."""
        if not collection:
            return
            
        count = collection.count()
        if count > self.max_patterns:
            all_data = collection.get(include=['metadatas'])
            
            if all_data and all_data.get('ids'):
                sorted_items = sorted(
                    zip(all_data['ids'], all_data['metadatas']),
                    key=lambda x: x[1].get('timestamp', ''),
                )
                
                to_delete = count - self.max_patterns + 50
                ids_to_delete = [item[0] for item in sorted_items[:to_delete]]
                
                if ids_to_delete:
                    collection.delete(ids=ids_to_delete)
                    logger.info(f"[Patterns] Evicted {len(ids_to_delete)} old patterns")
    
    def get_stats(self) -> Dict:
        """Get pattern store statistics."""
        return {
            "query_patterns": self.query_collection.count() if self.query_collection else 0,
            "alarm_patterns": self.alarm_collection.count() if self.alarm_collection else 0,
            "max_patterns": self.max_patterns,
            "persist_dir": str(self.persist_dir),
            "chromadb_available": CHROMADB_AVAILABLE,
        }
    
    def clear_all(self):
        """Clear all patterns (for testing or reset)."""
        if self.client:
            for name in [self.COLLECTION_QUERIES, self.COLLECTION_ALARMS]:
                try:
                    self.client.delete_collection(name)
                except (ValueError, AttributeError, RuntimeError) as e:
                    logger.debug(f"Collection {name} deletion skipped: {e}")
            self._init_chromadb()
            logger.info("[Patterns] All patterns cleared")


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_pattern_store: Optional[OperatorPatternStore] = None


def get_pattern_store(persist_dir: str = None) -> OperatorPatternStore:
    """Get or create the singleton pattern store instance."""
    global _pattern_store
    
    if _pattern_store is None:
        _pattern_store = OperatorPatternStore(persist_dir)
    
    return _pattern_store
