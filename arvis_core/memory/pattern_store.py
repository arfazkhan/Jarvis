"""
Pattern Store - Dynamic Few-Shot Learning Memory

Stores successful command→tool mappings and retrieves similar patterns
for few-shot injection into local agent prompts. Implements the "Update"
loop from the Titans architecture.

This enables the local agent to learn from past successful interactions
without requiring model fine-tuning.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("[PatternStore] ChromaDB not available")


class PatternStore:
    """
    Stores successful command patterns for dynamic few-shot learning.
    
    When a command is successfully executed locally:
    1. Store (command, tool_calls) pair in ChromaDB
    2. When similar commands come in, retrieve past patterns
    3. Inject as few-shot examples in prompt
    
    This creates a learning loop without model fine-tuning.
    """
    
    COLLECTION_NAME = "command_patterns"
    
    def __init__(self, persist_dir: str, max_patterns: int = 1000):
        """
        Initialize pattern store.
        
        Args:
            persist_dir: Directory for ChromaDB persistence
            max_patterns: Maximum patterns to store (FIFO eviction)
        """
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.max_patterns = max_patterns
        
        self.client = None
        self.collection = None
        
        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        
        logger.info(f"[PatternStore] Initialized at {self.persist_dir}")
    
    def _init_chromadb(self):
        """Initialize ChromaDB client and collection."""
        try:
            self.client = chromadb.PersistentClient(
                path=str(self.persist_dir / "patterns_db"),
                settings=Settings(anonymized_telemetry=False)
            )
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Command patterns for few-shot learning"}
            )
            logger.info(f"[PatternStore] ChromaDB collection ready: {self.collection.count()} patterns")
        except Exception as e:
            logger.error(f"[PatternStore] ChromaDB init failed: {e}")
            self.client = None
            self.collection = None
    
    def _generate_id(self, command: str) -> str:
        """Generate deterministic ID from command."""
        return hashlib.md5(command.lower().strip().encode()).hexdigest()[:12]
    
    def log_success(self, command: str, tool_calls: List[Dict], 
                    resolved_device: Optional[str] = None) -> bool:
        """
        Store a successful command pattern.
        
        Args:
            command: User's original command
            tool_calls: List of tool calls that were executed
            resolved_device: The actual device ID (after alias resolution)
            
        Returns:
            Success boolean
        """
        if not self.collection:
            return False
        
        try:
            # Skip if command is too short or empty
            command = command.strip()
            if len(command) < 3:
                return False
            
            # Create pattern document
            pattern_id = f"pat_{self._generate_id(command)}_{datetime.now().strftime('%H%M%S')}"
            
            # Extract tool info
            tool_name = tool_calls[0].get('tool', 'unknown') if tool_calls else 'unknown'
            device_id = tool_calls[0].get('args', {}).get('device_id', '') if tool_calls else ''
            
            # Store the pattern
            metadata = {
                "tool": tool_name,
                "device_id": device_id,
                "resolved_device": resolved_device or device_id,
                "tool_calls_json": json.dumps(tool_calls),
                "timestamp": datetime.now().isoformat(),
                "success": True
            }
            
            # Add to collection (upsert to handle duplicates)
            self.collection.add(
                documents=[command],
                metadatas=[metadata],
                ids=[pattern_id]
            )
            
            # Evict old patterns if over limit
            self._evict_if_needed()
            
            logger.debug(f"[PatternStore] Logged: '{command}' → {tool_name}({device_id})")
            return True
            
        except Exception as e:
            logger.error(f"[PatternStore] Failed to log pattern: {e}")
            return False
    
    def get_similar_patterns(self, command: str, k: int = 3, 
                             min_similarity: float = 0.5) -> List[Dict]:
        """
        Retrieve similar successful patterns for few-shot injection.
        
        Args:
            command: Current user command
            k: Number of patterns to retrieve
            min_similarity: Minimum similarity threshold (0-1)
            
        Returns:
            List of similar patterns with their tool calls
        """
        if not self.collection or self.collection.count() == 0:
            return []
        
        try:
            results = self.collection.query(
                query_texts=[command],
                n_results=min(k, self.collection.count())
            )
            
            patterns = []
            if results and results.get('documents'):
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
                    distance = results['distances'][0][i] if results.get('distances') else 1.0
                    
                    # Convert distance to similarity (ChromaDB uses L2 distance)
                    # Lower distance = more similar, typically 0-2 range
                    similarity = max(0, 1 - (distance / 2))
                    
                    if similarity >= min_similarity:
                        patterns.append({
                            "command": doc,
                            "tool": metadata.get('tool', 'unknown'),
                            "device_id": metadata.get('device_id', ''),
                            "resolved_device": metadata.get('resolved_device', ''),
                            "tool_calls": json.loads(metadata.get('tool_calls_json', '[]')),
                            "similarity": round(similarity, 3)
                        })
            
            # Sort by similarity (highest first)
            patterns.sort(key=lambda x: x['similarity'], reverse=True)
            
            return patterns
            
        except Exception as e:
            logger.error(f"[PatternStore] Failed to retrieve patterns: {e}")
            return []
    
    def format_as_fewshot(self, patterns: List[Dict]) -> str:
        """
        Format retrieved patterns as few-shot examples for prompt injection.
        
        Args:
            patterns: List of pattern dicts from get_similar_patterns
            
        Returns:
            Formatted string for prompt insertion
        """
        if not patterns:
            return ""
        
        lines = ["## Learned patterns from past successes:"]
        
        for p in patterns[:3]:  # Max 3 examples
            tool_call = {
                "tool": p['tool'],
                "args": {"device_id": p.get('resolved_device') or p['device_id']}
            }
            lines.append(f"User: {p['command']}")
            lines.append(f"Assistant: {json.dumps(tool_call)}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _evict_if_needed(self):
        """Remove oldest patterns if over limit."""
        if not self.collection:
            return
            
        count = self.collection.count()
        if count > self.max_patterns:
            # Get all patterns sorted by timestamp
            all_data = self.collection.get(
                include=['metadatas']
            )
            
            if all_data and all_data.get('ids'):
                # Sort by timestamp
                sorted_items = sorted(
                    zip(all_data['ids'], all_data['metadatas']),
                    key=lambda x: x[1].get('timestamp', ''),
                )
                
                # Delete oldest
                to_delete = count - self.max_patterns + 50  # Delete 50 extra for efficiency
                ids_to_delete = [item[0] for item in sorted_items[:to_delete]]
                
                if ids_to_delete:
                    self.collection.delete(ids=ids_to_delete)
                    logger.info(f"[PatternStore] Evicted {len(ids_to_delete)} old patterns")
    
    def get_stats(self) -> Dict:
        """Get pattern store statistics."""
        return {
            "total_patterns": self.collection.count() if self.collection else 0,
            "max_patterns": self.max_patterns,
            "persist_dir": str(self.persist_dir)
        }
    
    def clear_all(self):
        """Clear all patterns (for testing or reset)."""
        if self.collection:
            # Delete and recreate collection
            self.client.delete_collection(self.COLLECTION_NAME)
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Command patterns for few-shot learning"}
            )
            logger.info("[PatternStore] All patterns cleared")
