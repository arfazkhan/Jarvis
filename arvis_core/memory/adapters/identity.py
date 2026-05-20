"""
T6 Identity Store Adapter
==========================
Wraps PreferenceStore (arvis_core/memory) + OperatorPersona.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import (
    MemoryHit, MemoryRecord, MemoryTier, StoreHealth, ConversationContext,
)

logger = logging.getLogger("arvis.memory.adapters.identity")


class IdentityStoreAdapter:
    """T6 adapter. Wraps PreferenceStore.search() + OperatorPersona projection."""

    def __init__(self, preference_store=None, preference_learner=None):
        self._pref_store = preference_store     # arvis_core.memory.preference_store.PreferenceStore
        self._learner = preference_learner      # agent_advisory.preference_learner.PreferenceLearningEngine

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 3,
        operator_id: Optional[str] = None,
    ) -> List[MemoryHit]:
        hits: List[MemoryHit] = []

        if self._pref_store is not None:
            try:
                results = self._pref_store.search(query, limit=top_k)
                for r in results:
                    content = r.get("content") or r.get("value") or str(r)
                    hits.append(MemoryHit(
                        tier=MemoryTier.T6_IDENTITY,
                        content=content,
                        source="preference_store",
                        confidence=float(r.get("score", r.get("confidence", 0.6))),
                        metadata={"key": r.get("key"), "context": r.get("context")},
                    ))
            except Exception as e:
                logger.debug(f"[IdentityAdapter] PreferenceStore query failed: {e}")

        return hits[:top_k]

    async def write(self, record: MemoryRecord) -> str:
        if self._pref_store is None:
            return ""
        try:
            import uuid as _uuid
            pref_id = self._pref_store.add(
                content=record.content,
                key=f"pref_{_uuid.uuid4().hex[:8]}",
                context=record.source,
                confidence=record.confidence,
            )
            return pref_id or ""
        except Exception as e:
            logger.error(f"[IdentityAdapter] write failed: {e}")
            return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T6_IDENTITY,
            healthy=self._pref_store is not None,
        )
