"""
RAG Optimizer
=============

Sophisticated components for fine-tuning ARVIS retrieval:
1. Cross-Encoder Reranker: High-precision validation of retrieval candidates.
2. BMS Chunker: Domain-aware semantic chunking for technical manuals.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

logger = logging.getLogger("arvis.ml.rag_optimizer")

try:
    from sentence_transformers import CrossEncoder
    CE_AVAILABLE = True
except ImportError:
    CE_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Reranking will be disabled.")


# =============================================================================
# CROSS-ENCODER RERANKER
# =============================================================================

class CrossEncoderReranker:
    """
    Second-pass reranker for high-precision retrieval validation.
    
    Unlike Bi-Encoders (which encode query and doc separately), 
    Cross-Encoders ingest query+doc pairs and output a direct 
    relevance score.
    """
    
    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model = None
        if CE_AVAILABLE:
            try:
                self.model = CrossEncoder(model_name)
                logger.info(f"Loaded Cross-Encoder model: {model_name}")
            except Exception as e:
                logger.warning(f"Failed to load Cross-Encoder: {e}")
        
        self.is_available = self.model is not None
        
    def rerank(self, 
               query: str, 
               candidates: List[Dict[str, Any]], 
               top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Rerank retrieval candidates.
        
        Args:
            query: The user query
            candidates: List of skill/doc dictionaries to rerank
            top_n: Number of results to return
            
        Returns:
            Reranked and sorted candidates
        """
        if not self.is_available or not candidates:
            return candidates[:top_n]
            
        # Prepare pairs for cross-encoder
        # For skills, we use "title + description" as the text
        pairs = []
        for c in candidates:
            text = f"{c.get('title', '')} {c.get('description', '')}"
            pairs.append([query, text])
            
        # Predict relevance scores
        scores = self.model.predict(pairs)
        
        # Attach scores and sort
        for i, c in enumerate(candidates):
            c["rerank_score"] = float(scores[i])
            
        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        return candidates[:top_n]


# =============================================================================
# BMS SEMANTIC CHUNKER
# =============================================================================

class BMSChunker:
    """
    Domain-aware chunking for HVAC and BMS technical documentation.
    
    Prioritizes equipment boundaries and setpoint hierarchies 
    over arbitrary token counts.
    """
    
    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        self.chunk_size = chunk_size
        self.overlap = overlap
        
    def chunk_document(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Split document into semantic chunks.
        
        Logic:
        1. Split by section headers (e.g. "##", "AHU-", "ZONE-")
        2. Respect sentence boundaries.
        3. Attach metadata to every chunk.
        """
        import re
        
        # Initial split by obvious headers
        sections = re.split(r'\n(?=#{1,4} |[A-Z0-9]{2,}-\d{2})', text)
        
        chunks = []
        for section in sections:
            if not section.strip():
                continue
                
            # If section is small, keep it as is
            if len(section) <= self.chunk_size + self.overlap:
                chunks.append({
                    "text": section.strip(),
                    "metadata": metadata or {}
                })
            else:
                # Sub-chunking for large sections
                # (Simple sentence-based chunking for now)
                sentences = re.split(r'(?<=[.!?]) +', section)
                current_chunk = ""
                
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < self.chunk_size:
                        current_chunk += " " + sentence
                    else:
                        if current_chunk:
                            chunks.append({
                                "text": current_chunk.strip(),
                                "metadata": metadata or {}
                            })
                        current_chunk = sentence
                        
                if current_chunk:
                    chunks.append({
                        "text": current_chunk.strip(),
                        "metadata": metadata or {}
                    })
                    
        return chunks
