"""
T2 Episodic Store Adapter
==========================
Wraps investigation_plans / audit_spans / plan_evidence tables in SQLite.
Provides: archive_plan(), query() for similar past investigations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.episodic")


class EpisodicStoreAdapter:
    """T2 adapter. Wraps BMSDatabase investigation archive tables."""

    def __init__(self, db=None):
        self._db = db  # agent_commercial.database.BMSDatabase

    async def archive_plan(self, plan) -> str:
        """Persist completed InvestigationPlan to SQLite. Returns plan_id."""
        if self._db is None:
            return ""
        try:
            return await self._db.archive_investigation_plan(plan)
        except Exception as e:
            logger.error(f"[EpisodicAdapter] archive_plan failed: {e}")
            return ""

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 3,
    ) -> List[MemoryHit]:
        """Return similar past investigations as MemoryHit[]."""
        if self._db is None:
            return []
        try:
            plans = await self._db.get_investigation_plans(
                building_id=building_id,
                limit=top_k * 3,
                query_filter=None,
            )
            # Simple keyword overlap scoring (embedding similarity wired in Mem-2 extension)
            query_words = set(query.lower().split())
            scored = []
            for p in plans:
                plan_words = set((p.get("query") or "").lower().split())
                overlap = len(query_words & plan_words) / max(len(query_words), 1)
                scored.append((overlap, p))
            scored.sort(key=lambda x: x[0], reverse=True)

            hits = []
            for score, p in scored[:top_k]:
                if score < 0.1:
                    continue
                hits.append(MemoryHit(
                    tier=MemoryTier.T2_EPISODIC,
                    content=f"Past investigation: {p.get('query', '')} (status={p.get('status')}, evidence={p.get('evidence_count', 0)})",
                    source=f"investigation:{p.get('plan_id', '')}",
                    confidence=min(0.9, 0.4 + score * 0.5),
                    metadata={
                        "plan_id": p.get("plan_id"),
                        "status": p.get("status"),
                        "created_at": p.get("created_at"),
                        "evidence_count": p.get("evidence_count", 0),
                    },
                ))
            return hits
        except Exception as e:
            logger.debug(f"[EpisodicAdapter] query failed: {e}")
            return []

    async def write(self, record: MemoryRecord) -> str:
        return ""  # T2 writes go through archive_plan, not generic write

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T2_EPISODIC,
            healthy=self._db is not None,
        )
