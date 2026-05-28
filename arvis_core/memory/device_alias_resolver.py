"""
Device Alias Resolver - Smart Device Name Matching

Implements intelligent device name resolution using:
1. Learned aliases from successful patterns (PatternStore integration)
2. Semantic embeddings for similarity matching
3. User-taught aliases stored in preferences

This removes the need for hardcoded alias dictionaries.
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import sentence-transformers for embeddings
EMBEDDINGS_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    EMBEDDINGS_AVAILABLE = True
except Exception as e:
    logger.warning(f"[DeviceAliasResolver] sentence-transformers not available ({type(e).__name__}), using fallback matching")

# Module-level singleton — prevents repeated 90MB model loads across resolver instances.
_ALIAS_MODEL_CACHE: dict = {}

def _get_alias_model(model_name: str):
    import sys
    if not hasattr(sys, "_arvis_st_model_cache"):
        sys._arvis_st_model_cache = {}
    if model_name not in sys._arvis_st_model_cache and EMBEDDINGS_AVAILABLE:
        sys._arvis_st_model_cache[model_name] = SentenceTransformer(model_name)
    return sys._arvis_st_model_cache.get(model_name)

# Try to import ChromaDB for learned aliases
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class DeviceAliasResolver:
    """
    Resolves natural language device names to actual device IDs.
    
    Priority order:
    1. User-defined aliases (highest priority - explicit user preference)
    2. Learned aliases (from successful past resolutions)
    3. Semantic similarity matching (embedding-based)
    4. Fuzzy string matching (fallback)
    
    Example:
        resolver = DeviceAliasResolver(known_devices=["kitchen_main", "bedroom_lamp"])
        result = resolver.resolve("kitchen light")
        # Returns: ("kitchen_main", 0.92, "semantic")
    """
    
    COLLECTION_NAME = "device_aliases"
    
    def __init__(self, 
                 known_devices: List[str],
                 persist_dir: str = "./data/memories",
                 embedding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialize the resolver.
        
        Args:
            known_devices: List of valid device IDs
            persist_dir: Directory for ChromaDB persistence
            embedding_model: Sentence transformer model name
        """
        self.known_devices = known_devices
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # User-defined aliases (in-memory, synced with preferences)
        self.user_aliases: Dict[str, str] = {}
        
        # Learned aliases from patterns
        self.learned_aliases: Dict[str, Tuple[str, int]] = {}  # phrase -> (device_id, count)
        
        # Initialize embedding model
        self.embedding_model = None
        self.device_embeddings = None
        if EMBEDDINGS_AVAILABLE:
            self._init_embeddings(embedding_model)
        
        # Initialize ChromaDB for learned aliases
        self.client = None
        self.collection = None
        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        
        logger.info(f"[DeviceAliasResolver] Initialized with {len(known_devices)} devices")
    
    def _init_embeddings(self, model_name: str):
        """Initialize sentence transformer and compute device embeddings."""
        try:
            logger.info(f"[DeviceAliasResolver] Loading embedding model: {model_name} (singleton)")
            self.embedding_model = _get_alias_model(model_name)
            
            # Pre-compute embeddings for all known devices
            # Convert device IDs to natural language for better matching
            device_phrases = [self._device_to_natural(d) for d in self.known_devices]
            self.device_embeddings = self.embedding_model.encode(device_phrases)
            
            logger.info(f"[DeviceAliasResolver] Computed embeddings for {len(self.known_devices)} devices")
        except Exception as e:
            logger.error(f"[DeviceAliasResolver] Failed to init embeddings: {e}")
            self.embedding_model = None
    
    def _device_to_natural(self, device_id: str) -> str:
        """Convert device_id to natural language phrase for embedding."""
        # "kitchen_main" -> "kitchen main light"
        # "bedroom_ac" -> "bedroom ac air conditioner"
        phrase = device_id.replace("_", " ")
        
        # Add common synonyms for better matching
        if "light" not in phrase and "lamp" not in phrase:
            if any(room in phrase for room in ["kitchen", "bedroom", "bathroom", "living", "porch", "garage"]):
                phrase += " light"
        
        if "ac" in phrase:
            phrase += " air conditioner"
        
        return phrase
    
    def _init_chromadb(self):
        """Initialize ChromaDB for learned aliases."""
        try:
            self.client = chromadb.PersistentClient(
                path=str(self.persist_dir / "alias_db"),
                settings=Settings(anonymized_telemetry=False)
            )
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Learned device aliases"}
            )
            
            # Load existing learned aliases
            self._load_learned_aliases()
            
            logger.info(f"[DeviceAliasResolver] Loaded {len(self.learned_aliases)} learned aliases")
        except Exception as e:
            logger.error(f"[DeviceAliasResolver] ChromaDB init failed: {e}")
    
    def _load_learned_aliases(self):
        """Load learned aliases from ChromaDB."""
        if not self.collection:
            return
        
        try:
            results = self.collection.get(include=['metadatas'])
            if results and results.get('ids'):
                for i, doc_id in enumerate(results['ids']):
                    metadata = results['metadatas'][i]
                    phrase = metadata.get('phrase', '')
                    device_id = metadata.get('device_id', '')
                    count = metadata.get('count', 1)
                    if phrase and device_id:
                        self.learned_aliases[phrase.lower()] = (device_id, count)
        except Exception as e:
            logger.error(f"[DeviceAliasResolver] Failed to load aliases: {e}")
    
    def resolve(self, user_phrase: str, min_confidence: float = 0.6) -> Optional[Tuple[str, float, str]]:
        """
        Resolve a user phrase to a device ID.
        
        Args:
            user_phrase: Natural language device reference
            min_confidence: Minimum confidence threshold
            
        Returns:
            Tuple of (device_id, confidence, source) or None
            source is one of: "user", "learned", "semantic", "fuzzy"
        """
        phrase = user_phrase.lower().strip()
        
        # 1. Check user-defined aliases (highest priority)
        if phrase in self.user_aliases:
            return (self.user_aliases[phrase], 1.0, "user")
        
        # 2. Check learned aliases
        if phrase in self.learned_aliases:
            device_id, count = self.learned_aliases[phrase]
            # Higher confidence for more frequently used aliases
            confidence = min(0.95, 0.7 + (count * 0.05))
            return (device_id, confidence, "learned")
        
        # 3. Check exact match with known devices
        if phrase in self.known_devices:
            return (phrase, 1.0, "exact")
        
        # 4. Semantic similarity matching
        if self.embedding_model is not None and self.device_embeddings is not None:
            result = self._semantic_match(phrase, min_confidence)
            if result:
                return result
        
        # 5. Fuzzy string matching (fallback)
        result = self._fuzzy_match(phrase, min_confidence)
        if result:
            return result
        
        return None
    
    def _semantic_match(self, phrase: str, min_confidence: float) -> Optional[Tuple[str, float, str]]:
        """Find best match using semantic embeddings."""
        try:
            # Encode the user phrase
            phrase_embedding = self.embedding_model.encode([phrase])[0]
            
            # Compute cosine similarities
            similarities = np.dot(self.device_embeddings, phrase_embedding) / (
                np.linalg.norm(self.device_embeddings, axis=1) * np.linalg.norm(phrase_embedding)
            )
            
            best_idx = np.argmax(similarities)
            best_score = similarities[best_idx]
            
            if best_score >= min_confidence:
                return (self.known_devices[best_idx], float(best_score), "semantic")
            
        except Exception as e:
            logger.error(f"[DeviceAliasResolver] Semantic match failed: {e}")
        
        return None
    
    def _fuzzy_match(self, phrase: str, min_confidence: float) -> Optional[Tuple[str, float, str]]:
        """Fuzzy string matching as fallback."""
        from difflib import SequenceMatcher
        
        best_match = None
        best_ratio = 0.0
        
        for device_id in self.known_devices:
            # Compare against device_id and natural form
            natural = self._device_to_natural(device_id)
            
            ratio1 = SequenceMatcher(None, phrase, device_id.replace("_", " ")).ratio()
            ratio2 = SequenceMatcher(None, phrase, natural).ratio()
            ratio = max(ratio1, ratio2)
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = device_id
        
        if best_ratio >= min_confidence:
            return (best_match, best_ratio, "fuzzy")
        
        return None
    
    def learn_alias(self, phrase: str, device_id: str):
        """
        Learn a new alias from a successful resolution.
        Called after successful command execution.
        
        Args:
            phrase: The natural language phrase used
            device_id: The device it resolved to
        """
        phrase = phrase.lower().strip()
        
        # Skip if it's just the device ID itself
        if phrase == device_id or phrase == device_id.replace("_", " "):
            return
        
        # Update in-memory
        if phrase in self.learned_aliases:
            _, count = self.learned_aliases[phrase]
            self.learned_aliases[phrase] = (device_id, count + 1)
        else:
            self.learned_aliases[phrase] = (device_id, 1)
        
        # Persist to ChromaDB
        if self.collection:
            try:
                alias_id = f"alias_{hash(phrase) % 10000000}"
                _, count = self.learned_aliases[phrase]
                
                self.collection.upsert(
                    ids=[alias_id],
                    documents=[phrase],
                    metadatas=[{
                        "phrase": phrase,
                        "device_id": device_id,
                        "count": count
                    }]
                )
                logger.debug(f"[DeviceAliasResolver] Learned: '{phrase}' → {device_id} (count: {count})")
            except Exception as e:
                logger.error(f"[DeviceAliasResolver] Failed to persist alias: {e}")
    
    def add_user_alias(self, phrase: str, device_id: str) -> bool:
        """
        Add a user-defined alias (highest priority).
        Called when user explicitly teaches an alias.
        
        Args:
            phrase: The alias phrase (e.g., "reading lamp")
            device_id: The target device (e.g., "bedroom_lamp")
            
        Returns:
            Success boolean
        """
        phrase = phrase.lower().strip()
        
        # Validate device exists
        if device_id not in self.known_devices:
            logger.warning(f"[DeviceAliasResolver] Unknown device: {device_id}")
            return False
        
        self.user_aliases[phrase] = device_id
        logger.info(f"[DeviceAliasResolver] User alias: '{phrase}' → {device_id}")
        return True
    
    def remove_user_alias(self, phrase: str) -> bool:
        """Remove a user-defined alias."""
        phrase = phrase.lower().strip()
        if phrase in self.user_aliases:
            del self.user_aliases[phrase]
            return True
        return False
    
    def get_stats(self) -> Dict:
        """Get resolver statistics."""
        return {
            "known_devices": len(self.known_devices),
            "user_aliases": len(self.user_aliases),
            "learned_aliases": len(self.learned_aliases),
            "embeddings_available": self.embedding_model is not None,
            "top_learned": sorted(
                [(p, d, c) for p, (d, c) in self.learned_aliases.items()],
                key=lambda x: x[2],
                reverse=True
            )[:5]
        }
    
    def update_known_devices(self, devices: List[str]):
        """Update the list of known devices and recompute embeddings."""
        self.known_devices = devices
        if EMBEDDINGS_AVAILABLE and self.embedding_model:
            device_phrases = [self._device_to_natural(d) for d in devices]
            self.device_embeddings = self.embedding_model.encode(device_phrases)
