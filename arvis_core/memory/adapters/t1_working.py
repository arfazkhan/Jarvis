"""
T1 Working Memory Adapter
=========================
Wraps BMSDatabase conversation_turns table.
Provides: load_conversation(), append_turn() for cross-session chat context.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from arvis_core.memory.types import ConversationContext, MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.t1_working")

SUMMARY_WINDOW = 10   # collapse oldest turns into summary after this many turns
LOAD_LIMIT = 20       # max turns loaded per session


class T1WorkingAdapter:
    """T1 adapter. Wraps BMSDatabase conversation_turns table."""

    def __init__(self, db=None):
        self._db = db

    async def load_conversation(self, operator_id: str, building_id: str) -> ConversationContext:
        """Load recent turns for an operator+building pair. Returns empty context if DB unavailable."""
        if self._db is None:
            return ConversationContext(operator_id=operator_id, building_id=building_id)
        try:
            rows = await self._db.load_conversation_turns(operator_id, building_id, limit=LOAD_LIMIT)
            summary = ""
            turns = []
            for r in rows:
                if r.get("is_summary"):
                    summary = r["content"]
                else:
                    turns.append({"role": r["role"], "content": r["content"]})
            return ConversationContext(
                operator_id=operator_id,
                building_id=building_id,
                turns=turns,
                rolling_summary=summary,
            )
        except Exception as e:
            logger.debug(f"[T1WorkingAdapter] load_conversation failed: {e}")
            return ConversationContext(operator_id=operator_id, building_id=building_id)

    async def append_turn(
        self,
        operator_id: str,
        building_id: str,
        role: str,
        content: str,
    ) -> None:
        """Persist one turn. Triggers rolling summarization when window fills."""
        if self._db is None:
            return
        try:
            await self._db.save_conversation_turn(operator_id, building_id, role, content)
            await self._maybe_summarize(operator_id, building_id)
        except Exception as e:
            logger.debug(f"[T1WorkingAdapter] append_turn failed: {e}")

    async def _maybe_summarize(self, operator_id: str, building_id: str) -> None:
        """If non-summary turns >= SUMMARY_WINDOW, collapse oldest half into a summary row."""
        if self._db is None:
            return
        try:
            rows = await self._db.load_conversation_turns(operator_id, building_id, limit=LOAD_LIMIT)
            non_summary = [r for r in rows if not r.get("is_summary")]
            if len(non_summary) < SUMMARY_WINDOW:
                return

            to_collapse = non_summary[: len(non_summary) // 2]
            summary_text = "; ".join(
                f"{r['role']}: {r['content'][:120]}" for r in to_collapse
            )
            # Write new summary row (replaces older entries conceptually — query only loads recent rows)
            await self._db.save_conversation_turn(
                operator_id, building_id,
                role="system",
                content=f"[Summary of prior turns] {summary_text}",
                is_summary=True,
                summary_range=f"oldest_{len(to_collapse)}_turns",
            )
        except Exception as e:
            logger.debug(f"[T1WorkingAdapter] summarize failed: {e}")

    async def query(self, query: str, **kwargs) -> List[MemoryHit]:
        return []

    async def write(self, record: MemoryRecord) -> str:
        return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T1_WORKING,
            healthy=self._db is not None,
        )
