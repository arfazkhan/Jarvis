"""
T3 Procedural Store Adapter
============================
Wraps distilled_rules (SQLite) + OperatorPatternStore (Chroma).
Returns MemoryHit[] — no data migration, thin layer only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.procedural")


class ProceduralStoreAdapter:
    """
    T3 adapter. Accepts injected db + pattern_store at init.
    Both are optional — degrades gracefully if not wired.
    """

    def __init__(self, db=None, pattern_store=None):
        self._db = db                     # agent_commercial.database.BMSDatabase
        self._pattern_store = pattern_store  # agent_commercial.learning.operator_patterns.OperatorPatternStore

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[MemoryHit]:
        hits: List[MemoryHit] = []

        # ── distilled_rules via DB ────────────────────────────────────────
        if self._db is not None:
            try:
                rules = await self._db.get_distilled_rules(agent_name="arvis")
                for rule in rules[:top_k]:
                    content = rule.get("rule_text") or rule.get("content") or str(rule)
                    hits.append(MemoryHit(
                        tier=MemoryTier.T3_PROCEDURAL,
                        content=content,
                        source="distilled_rules",
                        confidence=float(rule.get("confidence", 0.7)),
                        metadata={"rule_id": rule.get("id"), "hit_count": rule.get("hit_count", 0)},
                    ))
            except Exception as e:
                logger.debug(f"[ProceduralAdapter] distilled_rules query failed: {e}")

        # ── OperatorPatternStore (Chroma) ────────────────────────────────
        if self._pattern_store is not None:
            try:
                patterns = self._pattern_store.get_similar_queries(query, k=top_k, min_similarity=0.4)
                for p in patterns:
                    hits.append(MemoryHit(
                        tier=MemoryTier.T3_PROCEDURAL,
                        content=p.get("query", "") or p.get("content", ""),
                        source="operator_patterns",
                        confidence=float(p.get("similarity", p.get("score", 0.5))),
                        metadata=p,
                    ))
            except Exception as e:
                logger.debug(f"[ProceduralAdapter] OperatorPatternStore query failed: {e}")

        hits.sort(key=lambda h: h.confidence, reverse=True)
        return hits[:top_k]

    async def write(self, record: MemoryRecord) -> str:
        if self._db is None:
            return ""
        try:
            import uuid as _uuid
            rule_id = f"rule_{_uuid.uuid4().hex[:10]}"
            await self._db.save_distilled_rule({
                "id": rule_id,
                "rule_text": record.content,
                "confidence": record.confidence,
                "source": record.source,
                "building_id": record.building_id,
                "evidence_ids": record.evidence_ids,
            })
            return rule_id
        except Exception as e:
            logger.error(f"[ProceduralAdapter] write failed: {e}")
            return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T3_PROCEDURAL,
            healthy=self._db is not None or self._pattern_store is not None,
            record_count=-1,
        )
