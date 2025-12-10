"""
Preference Store - ChromaDB-backed semantic memory
Long-term user preferences with vector search.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PreferenceStore:
    """
    Semantic preference storage using ChromaDB.
    
    Features:
    - Natural language queries ("what brightness does user like?")
    - Automatic embeddings (Sentence Transformers)
    - Persistent storage
    - Metadata filtering
    
    Example:
        store = PreferenceStore("./data/memories")
        store.add("I like 40% brightness in the evening", 
                  key="evening_brightness", context="bedroom")
        
        matches = store.search("brightness preferences")
    """
    
    def __init__(self, persist_dir: str = "./data/memories"):
        self.persist_dir = persist_dir
        self._collection = None
        self._client = None
        self._fallback_mode = False
        self._fallback_data = []
        
        os.makedirs(persist_dir, exist_ok=True)
        self._init_chromadb()
    
    def _init_chromadb(self):
        """Initialize ChromaDB with fallback to JSON if unavailable."""
        try:
            import chromadb
            from chromadb.config import Settings
            
            self._client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._client.get_or_create_collection(
                name="preferences",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"[PreferenceStore] ChromaDB initialized at {self.persist_dir}")
            
        except ImportError:
            logger.warning("[PreferenceStore] ChromaDB not installed, using JSON fallback")
            self._fallback_mode = True
            self._load_fallback()
        except Exception as e:
            logger.error(f"[PreferenceStore] ChromaDB init failed: {e}, using fallback")
            self._fallback_mode = True
            self._load_fallback()
    
    def _load_fallback(self):
        """Load preferences from JSON fallback."""
        fallback_path = os.path.join(self.persist_dir, "preferences_fallback.json")
        if os.path.exists(fallback_path):
            with open(fallback_path, 'r') as f:
                self._fallback_data = json.load(f)
    
    def _save_fallback(self):
        """Save preferences to JSON fallback."""
        fallback_path = os.path.join(self.persist_dir, "preferences_fallback.json")
        with open(fallback_path, 'w') as f:
            json.dump(self._fallback_data, f, indent=2)
    
    def add(self, content: str, key: str, context: str = "general", 
            confidence: float = 1.0, metadata: Optional[Dict] = None) -> str:
        """
        Add a preference to memory.
        
        Args:
            content: Natural language preference (e.g., "I like warm lights")
            key: Preference key for direct lookup
            context: When this applies (e.g., "evening", "bedroom")
            confidence: How confident we are (0-1)
            metadata: Additional metadata
            
        Returns:
            Preference ID
        """
        pref_id = f"pref_{key}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        meta = {
            "key": key,
            "context": context,
            "confidence": confidence,
            "created_at": datetime.now().isoformat(),
            **(metadata or {})
        }
        
        if self._fallback_mode:
            self._fallback_data.append({
                "id": pref_id,
                "content": content,
                "metadata": meta
            })
            self._save_fallback()
        else:
            self._collection.add(
                documents=[content],
                metadatas=[meta],
                ids=[pref_id]
            )
        
        logger.info(f"[PreferenceStore] Added: {key} = '{content[:50]}...'")
        return pref_id
    
    def search(self, query: str, limit: int = 5, 
               context_filter: Optional[str] = None) -> List[Dict]:
        """
        Semantic search for preferences.
        
        Args:
            query: Natural language query
            limit: Max results
            context_filter: Optional context filter
            
        Returns:
            List of matching preferences with scores
        """
        if self._fallback_mode:
            # Simple keyword matching for fallback
            results = []
            query_lower = query.lower()
            for item in self._fallback_data:
                if query_lower in item["content"].lower():
                    results.append({
                        "id": item["id"],
                        "content": item["content"],
                        "metadata": item["metadata"],
                        "score": 0.8
                    })
            return results[:limit]
        
        # ChromaDB semantic search
        where_filter = None
        if context_filter:
            where_filter = {"context": context_filter}
        
        results = self._collection.query(
            query_texts=[query],
            n_results=limit,
            where=where_filter
        )
        
        matches = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                matches.append({
                    "id": results['ids'][0][i],
                    "content": doc,
                    "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                    "score": 1 - (results['distances'][0][i] if results['distances'] else 0)
                })
        
        return matches
    
    def get_by_key(self, key: str) -> Optional[Dict]:
        """Get preference by exact key."""
        if self._fallback_mode:
            for item in self._fallback_data:
                if item["metadata"].get("key") == key:
                    return item
            return None
        
        results = self._collection.get(
            where={"key": key},
            limit=1
        )
        
        if results and results['documents']:
            return {
                "id": results['ids'][0],
                "content": results['documents'][0],
                "metadata": results['metadatas'][0] if results['metadatas'] else {}
            }
        return None
    
    def delete(self, pref_id: str) -> bool:
        """Delete a preference by ID."""
        if self._fallback_mode:
            self._fallback_data = [p for p in self._fallback_data if p["id"] != pref_id]
            self._save_fallback()
            return True
        
        try:
            self._collection.delete(ids=[pref_id])
            logger.info(f"[PreferenceStore] Deleted: {pref_id}")
            return True
        except Exception as e:
            logger.error(f"[PreferenceStore] Delete failed: {e}")
            return False
    
    def delete_by_key(self, key: str) -> bool:
        """Delete all preferences with a given key."""
        if self._fallback_mode:
            original_len = len(self._fallback_data)
            self._fallback_data = [p for p in self._fallback_data 
                                   if p["metadata"].get("key") != key]
            self._save_fallback()
            return len(self._fallback_data) < original_len
        
        try:
            self._collection.delete(where={"key": key})
            return True
        except:
            return False
    
    def list_all(self) -> List[Dict]:
        """List all preferences."""
        if self._fallback_mode:
            return self._fallback_data
        
        results = self._collection.get()
        prefs = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents']):
                prefs.append({
                    "id": results['ids'][i],
                    "content": doc,
                    "metadata": results['metadatas'][i] if results['metadatas'] else {}
                })
        return prefs
    
    def export_all(self) -> Dict:
        """Export all preferences as JSON (GDPR Article 20)."""
        return {
            "type": "preferences",
            "count": len(self.list_all()),
            "data": self.list_all(),
            "exported_at": datetime.now().isoformat()
        }
    
    def clear_all(self) -> bool:
        """Delete all preferences (GDPR Article 17)."""
        if self._fallback_mode:
            self._fallback_data = []
            self._save_fallback()
            return True
        
        try:
            # ChromaDB doesn't have clear, recreate collection
            self._client.delete_collection("preferences")
            self._collection = self._client.create_collection(
                name="preferences",
                metadata={"hnsw:space": "cosine"}
            )
            return True
        except Exception as e:
            logger.error(f"[PreferenceStore] Clear failed: {e}")
            return False
