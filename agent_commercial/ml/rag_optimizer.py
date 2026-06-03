"""
RAG Optimizer
=============

Sophisticated components for fine-tuning ARVIS retrieval:
1. Cross-Encoder Reranker: BAAI/bge-reranker-v2-m3 (local, zero-cost).
                           Falls back to Amazon Rerank v1.0 via Bedrock if unavailable.
2. BMS Chunker: Domain-aware semantic chunking for technical manuals.
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger("arvis.ml.rag_optimizer")

_BGE_MODEL_NAME   = "BAAI/bge-reranker-v2-m3"
_AMAZON_RERANK_MODEL = "amazon.rerank-v1:0"


# =============================================================================
# CROSS-ENCODER RERANKER
# Primary  : BAAI/bge-reranker-v2-m3  (local, sentence-transformers)
# Fallback : Amazon Rerank v1.0        (Bedrock, cloud)
# =============================================================================

class CrossEncoderReranker:
    """
    Second-pass reranker with two-tier strategy:

    Tier 1 — Local (preferred):
        BAAI/bge-reranker-v2-m3 via sentence-transformers CrossEncoder.
        Zero API cost, ~50-200 ms on CPU, SOTA quality on technical text.
        Model (~1.1 GB) is downloaded on first use and cached locally.

    Tier 2 — Cloud fallback:
        Amazon Rerank v1.0 via AWS Bedrock.
        Used automatically if sentence-transformers is not installed
        or the local model fails to load.
    """

    def __init__(self):
        self._local_model  = None   # CrossEncoder instance (lazy loaded)
        self._local_ok     = None   # None = untried, True/False after first attempt
        self._bedrock_client  = None
        self._bedrock_region  = os.environ.get("AWS_BEDROCK_REGION", "us-west-2")
        self.is_available  = True   # always True — one of the two tiers will work

    # ------------------------------------------------------------------
    # Tier 1: local BGE
    # ------------------------------------------------------------------

    def _get_local_model(self):
        if self._local_ok is False:
            return None
        if self._local_model is None:
            try:
                from sentence_transformers import CrossEncoder
                logger.info(f"[Reranker] Loading {_BGE_MODEL_NAME} …")
                self._local_model = CrossEncoder(_BGE_MODEL_NAME)
                self._local_ok    = True
                logger.info("[Reranker] BGE model ready.")
            except Exception as e:
                logger.warning(f"[Reranker] Could not load BGE model: {e}. Will use Bedrock fallback.")
                self._local_ok = False
        return self._local_model

    def _rerank_local(self, query: str, documents: List[str], top_n: int,
                      candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        model  = self._get_local_model()
        pairs  = [(query, doc) for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False).tolist()

        ranked = sorted(
            zip(scores, candidates),
            key=lambda x: x[0],
            reverse=True,
        )
        result = []
        for score, cand in ranked[:top_n]:
            cand["rerank_score"] = float(score)
            result.append(cand)
        return result

    # ------------------------------------------------------------------
    # Tier 2: Amazon Rerank via Bedrock
    # ------------------------------------------------------------------

    def _get_bedrock_client(self):
        if self._bedrock_client is None:
            try:
                import boto3
                from botocore.config import Config
                self._bedrock_client = boto3.client(
                    "bedrock-runtime",
                    region_name=self._bedrock_region,
                    config=Config(read_timeout=30, connect_timeout=5, retries={"max_attempts": 2}),
                )
            except Exception as e:
                logger.warning(f"[Reranker] Bedrock client init failed: {e}")
        return self._bedrock_client

    def _rerank_bedrock(self, query: str, documents: List[str], top_n: int,
                        candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        client = self._get_bedrock_client()
        if not client:
            return candidates[:top_n]

        payload = json.dumps({
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            "api_version": 2,
        })
        response = client.invoke_model(
            modelId=_AMAZON_RERANK_MODEL,
            contentType="application/json",
            accept="application/json",
            body=payload,
        )
        result = json.loads(response["body"].read())
        reranked = []
        for r in result.get("results", []):
            idx   = r.get("index", 0)
            score = r.get("relevance_score", 0.0)
            if idx < len(candidates):
                candidates[idx]["rerank_score"] = score
                reranked.append(candidates[idx])
        return reranked[:top_n]

    # ------------------------------------------------------------------
    # Public API (unchanged — callers need no modifications)
    # ------------------------------------------------------------------

    def rerank(self,
               query: str,
               candidates: List[Dict[str, Any]],
               top_n: int = 5) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        # Build plain-text document list once, reused by both tiers
        documents = []
        for c in candidates:
            text = f"{c.get('title', '')} {c.get('description', '')}".strip()
            if not text:
                text = c.get("content", c.get("text", str(c)))
            documents.append(text)

        # ── Tier 1: local BGE ──────────────────────────────────────────
        if self._local_ok is not False:
            try:
                results = self._rerank_local(query, documents, top_n, candidates)
                logger.debug(f"[Reranker] BGE reranked {len(candidates)} → {len(results)}")
                return results
            except Exception as e:
                logger.warning(f"[Reranker] BGE rerank failed: {e}. Trying Bedrock fallback …")
                self._local_ok = False  # don't retry broken model in same session

        # ── Tier 2: Amazon Rerank fallback ────────────────────────────
        try:
            results = self._rerank_bedrock(query, documents, top_n, candidates)
            logger.debug(f"[Reranker] Amazon Rerank fallback: {len(candidates)} → {len(results)}")
            return results
        except Exception as e:
            logger.warning(f"[Reranker] Bedrock fallback also failed: {e}. Returning original order.")
            self._broadcast_warning(str(e))
            return candidates[:top_n]

    def _broadcast_warning(self, detail: str) -> None:
        try:
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(SSEBroadcaster().broadcast("agent_log", {
                    "agent": "Memory_Agent",
                    "icon": "warning",
                    "colorClass": "text-amber-500 animate-pulse",
                    "text": "Reranker unavailable (both tiers failed)",
                    "subtext": f"BGE local + Amazon Bedrock both failed. Keyword order active. Detail: {detail}"
                }, channel="monitor"))
        except Exception:
            pass


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
