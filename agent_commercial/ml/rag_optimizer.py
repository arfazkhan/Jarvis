"""
RAG Optimizer
=============

Sophisticated components for fine-tuning ARVIS retrieval:
1. Cross-Encoder Reranker: Cohere Rerank v3.5 via Bedrock (replaces local CrossEncoder).
2. BMS Chunker: Domain-aware semantic chunking for technical manuals.
"""

import json
import logging
import os
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

logger = logging.getLogger("arvis.ml.rag_optimizer")

_COHERE_RERANK_MODEL = "cohere.rerank-v3-5:0"


# =============================================================================
# CROSS-ENCODER RERANKER (Cohere Rerank v3.5 via Bedrock)
# =============================================================================

class CrossEncoderReranker:
    """
    Second-pass reranker using Cohere Rerank v3.5 on Bedrock.
    No local model loading — API-based, fast, multilingual.
    """

    def __init__(self, model_id: str = _COHERE_RERANK_MODEL):
        self._model_id = model_id
        self._region = os.environ.get("AWS_BEDROCK_REGION", "us-west-2")
        self._client = None
        self.is_available = True

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self._region,
                    config=Config(read_timeout=30, connect_timeout=5, retries={"max_attempts": 2}),
                )
            except Exception as e:
                logger.warning(f"[Reranker] boto3 client init failed: {e}")
                self.is_available = False
        return self._client

    def rerank(self,
               query: str,
               candidates: List[Dict[str, Any]],
               top_n: int = 5) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        documents = []
        for c in candidates:
            text = f"{c.get('title', '')} {c.get('description', '')}".strip()
            if not text:
                text = c.get("content", c.get("text", str(c)))
            documents.append(text)

        client = self._get_client()
        if not client:
            return candidates[:top_n]

        try:
            payload = json.dumps({
                "query": query,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
            })
            response = client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=payload,
            )
            result = json.loads(response["body"].read())
            ranked_indices = result.get("results", [])

            reranked = []
            for r in ranked_indices:
                idx = r.get("index", 0)
                score = r.get("relevance_score", 0.0)
                if idx < len(candidates):
                    candidates[idx]["rerank_score"] = score
                    reranked.append(candidates[idx])

            return reranked[:top_n]

        except Exception as e:
            logger.warning(f"[Reranker] Cohere rerank failed: {e}. Falling back to original order.")
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
