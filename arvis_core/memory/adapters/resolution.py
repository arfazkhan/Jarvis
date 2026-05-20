"""
T7 Resolution Store Adapter
=============================
Wraps DeviceAliasResolver — NL phrase → canonical device ID.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.resolution")


class ResolutionStoreAdapter:
    """T7 adapter. Wraps DeviceAliasResolver.resolve()."""

    def __init__(self, resolver=None):
        self._resolver = resolver  # arvis_core.memory.device_alias_resolver.DeviceAliasResolver

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[MemoryHit]:
        if self._resolver is None:
            return []
        try:
            result = self._resolver.resolve(query, min_confidence=0.5)
            if result is None:
                return []
            canonical_id, confidence, alias = result
            return [MemoryHit(
                tier=MemoryTier.T7_RESOLUTION,
                content=f"{alias} → {canonical_id}",
                source="device_alias_resolver",
                confidence=float(confidence),
                metadata={"alias": alias, "canonical_id": canonical_id},
            )]
        except Exception as e:
            logger.debug(f"[ResolutionAdapter] resolve failed: {e}")
            return []

    async def write(self, record: MemoryRecord) -> str:
        # Alias registration not yet implemented — resolver is read-only
        logger.debug("[ResolutionAdapter] Write not supported yet")
        return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T7_RESOLUTION,
            healthy=self._resolver is not None,
        )
