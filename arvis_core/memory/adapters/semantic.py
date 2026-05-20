"""
T4 Semantic Store Adapter
==========================
Wraps HybridRAGRouter (TechnicalKnowledgeBase + TreeKnowledgeBase).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.semantic")


class SemanticStoreAdapter:
    """T4 adapter. Wraps HybridRAGRouter.retrieve()."""

    def __init__(self, hybrid_rag=None):
        self._rag = hybrid_rag  # agent_advisory.hybrid_rag.HybridRAGRouter

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[MemoryHit]:
        if self._rag is None:
            return []
        try:
            equipment_id = equipment_filter[0] if equipment_filter else None
            result = await self._rag.retrieve(
                query=query,
                equipment_id=equipment_id,
                limit=top_k,
                strategy="auto",
                use_llm_routing=False,  # avoid extra LLM call during recall
            )
            chunks = result.get("chunks") or result.get("results") or []
            hits = []
            for chunk in chunks[:top_k]:
                content = chunk.get("content") or chunk.get("text") or str(chunk)
                source_doc = chunk.get("source") or chunk.get("document_id") or "knowledge_base"
                confidence = float(chunk.get("score") or chunk.get("relevance", 0.5))
                hits.append(MemoryHit(
                    tier=MemoryTier.T4_SEMANTIC,
                    content=content[:500],
                    source=source_doc,
                    confidence=confidence,
                    metadata={
                        "page": chunk.get("page"),
                        "section": chunk.get("section"),
                        "strategy": result.get("strategy_used"),
                    },
                ))
            return hits
        except Exception as e:
            logger.debug(f"[SemanticAdapter] RAG query failed: {e}")
            return []

    async def write(self, record: MemoryRecord) -> str:
        # T4 writes go through ManualIngester — not direct here
        logger.debug("[SemanticAdapter] Direct write not supported; use ManualIngester pipeline")
        return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T4_SEMANTIC,
            healthy=self._rag is not None,
        )
