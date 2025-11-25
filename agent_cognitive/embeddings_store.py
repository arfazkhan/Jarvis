"""
Embeddings Store
----------------
Handles semantic vector storage and retrieval using FAISS.
Generates embeddings for text events to allow "fuzzy" memory lookup.
"""

import json
import time
import pickle
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Conditional imports to avoid crashing if dependencies aren't installed yet
try:
    import faiss
    from sentence_transformers import SentenceTransformer
except ImportError:
    faiss = None
    SentenceTransformer = None

from config.settings import get_config

CONFIG = get_config("cognitive")
EMBEDDING_CONFIG = CONFIG.get("embeddings", {})

STORAGE_PATH = Path(CONFIG.get("memory", {}).get("storage_path", "data/memory")).parent
INDEX_PATH = STORAGE_PATH / "faiss_index.bin"
METADATA_PATH = STORAGE_PATH / "faiss_metadata.pkl"

MODEL_NAME = EMBEDDING_CONFIG.get("model", "all-MiniLM-L6-v2")
EMBEDDING_DIM = EMBEDDING_CONFIG.get("embedding_dim", 384)


class EmbeddingsStore:
    def __init__(self):
        if not faiss or not SentenceTransformer:
            print("[EmbeddingsStore] WARNING: faiss or sentence-transformers not installed. Vector search disabled.")
            self.enabled = False
            return

        self.enabled = True
        self.model = SentenceTransformer(MODEL_NAME)
        self.index = None
        self.metadata = {}  # Map internal ID -> External Event ID / Metadata
        self._load_or_create_index()

    def _load_or_create_index(self):
        """Load existing FAISS index or create a new one"""
        if INDEX_PATH.exists() and METADATA_PATH.exists():
            try:
                self.index = faiss.read_index(str(INDEX_PATH))
                with open(METADATA_PATH, "rb") as f:
                    self.metadata = pickle.load(f)
                print(f"[EmbeddingsStore] Loaded index with {self.index.ntotal} vectors.")
            except Exception as e:
                print(f"[EmbeddingsStore] Error loading index: {e}. Creating new one.")
                self._create_new_index()
        else:
            self._create_new_index()

    def _create_new_index(self):
        """Create a fresh FAISS index"""
        # Using IndexFlatL2 for exact search (good for <1M vectors)
        # For larger datasets, use IndexIVFFlat
        self.index = faiss.IndexFlatL2(EMBEDDING_DIM)
        self.metadata = {}
        print("[EmbeddingsStore] Created new FAISS index.")

    def add_text(self, text: str, meta: Dict[str, Any]) -> str:
        """
        Embed text and add to index.
        Returns the internal embedding ID (as string).
        """
        if not self.enabled:
            return ""

        # 1. Generate embedding
        vector = self.model.encode([text])[0]
        
        # 2. Add to FAISS
        # FAISS expects float32 numpy array
        vector_np = np.array([vector], dtype="float32")
        self.index.add(vector_np)
        
        # 3. Store metadata
        # internal_id is the index in FAISS (0, 1, 2...)
        internal_id = self.index.ntotal - 1
        self.metadata[internal_id] = meta
        
        # 4. Auto-save (in production, might want to batch this)
        self._save_index()
        
        return str(internal_id)

    def search(self, query: str, limit: int = 5, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        Semantic search for query text.
        Returns list of metadata dicts with 'score' field.
        """
        if not self.enabled or self.index.ntotal == 0:
            return []

        # 1. Embed query
        query_vector = self.model.encode([query])
        query_np = np.array(query_vector, dtype="float32")
        
        # 2. Search
        distances, indices = self.index.search(query_np, limit)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx == -1: continue
            
            dist = distances[0][i]
            # Convert L2 distance to similarity score (approximate)
            # For normalized vectors, L2 = 2(1-cosine_sim)
            # Here we just use distance directly or invert it
            
            # Retrieve metadata
            meta = self.metadata.get(idx, {}).copy()
            meta["distance"] = float(dist)
            
            # Simple threshold check (lower distance = better match)
            # Adjust threshold logic based on your needs
            results.append(meta)
            
        return results

    def _save_index(self):
        """Persist index to disk"""
        STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(INDEX_PATH))
        with open(METADATA_PATH, "wb") as f:
            pickle.dump(self.metadata, f)

    def clear(self):
        """Clear all embeddings"""
        self._create_new_index()
        self._save_index()
