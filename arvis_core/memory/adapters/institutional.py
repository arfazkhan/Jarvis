"""
T5 Institutional Store Adapter
================================
Wraps BuildingSkillbook + scenario_retriever.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from arvis_core.memory.types import MemoryHit, MemoryRecord, MemoryTier, StoreHealth

logger = logging.getLogger("arvis.memory.adapters.institutional")


class InstitutionalStoreAdapter:
    """T5 adapter. Wraps BuildingSkillbook.query_skillbook() + scenario_retriever.retrieve_similar()."""

    def __init__(self, skillbook=None, scenario_retriever=None):
        self._skillbook = skillbook
        self._scenario_retriever = scenario_retriever

    async def query(
        self,
        query: str,
        building_id: str = "",
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[MemoryHit]:
        hits: List[MemoryHit] = []

        # ── BuildingSkillbook ─────────────────────────────────────────────
        if self._skillbook is not None:
            try:
                equipment_id = equipment_filter[0] if equipment_filter else None
                result = await self._skillbook.query_skillbook(
                    building_id=building_id or "default",
                    context={"query": query},
                    equipment_id=equipment_id,
                )
                skills = result.get("skills") or result.get("results") or []
                for skill in skills[:top_k]:
                    content = skill.get("description") or skill.get("content") or str(skill)
                    hits.append(MemoryHit(
                        tier=MemoryTier.T5_INSTITUTIONAL,
                        content=content[:500],
                        source="skillbook",
                        confidence=float(skill.get("confidence", skill.get("score", 0.7))),
                        metadata={
                            "skill_id": skill.get("skill_id") or skill.get("id"),
                            "skill_type": skill.get("skill_type"),
                            "equipment_id": skill.get("equipment_id"),
                        },
                    ))
            except Exception as e:
                logger.debug(f"[InstitutionalAdapter] Skillbook query failed: {e}")

        # ── ScenarioRetriever ────────────────────────────────────────────
        if self._scenario_retriever is not None:
            try:
                context = {"query": query, "building_id": building_id}
                if equipment_filter:
                    context["equipment_id"] = equipment_filter[0]
                scenarios = await self._scenario_retriever.retrieve_similar(
                    context=context, k=top_k
                )
                for scenario in scenarios[:top_k]:
                    content = getattr(scenario, "description", None) or str(scenario)
                    confidence = float(getattr(scenario, "similarity_score", 0.6))
                    hits.append(MemoryHit(
                        tier=MemoryTier.T5_INSTITUTIONAL,
                        content=content[:500],
                        source="scenario_retriever",
                        confidence=confidence,
                        metadata={"scenario_id": getattr(scenario, "id", None)},
                    ))
            except Exception as e:
                logger.debug(f"[InstitutionalAdapter] ScenarioRetriever failed: {e}")

        hits.sort(key=lambda h: h.confidence, reverse=True)
        return hits[:top_k]

    async def write(self, record: MemoryRecord) -> str:
        if self._skillbook is None:
            return ""
        try:
            skill_type = "pattern"
            if record.source and record.source.lower() in ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note", "schedule", "threshold"]:
                skill_type = record.source.lower()
            elif record.metadata and record.metadata.get("skill_type") in ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note", "schedule", "threshold"]:
                skill_type = record.metadata.get("skill_type")

            skills = await self._skillbook.add_skill(
                skill_type=skill_type,
                title=record.source or "Learned Memory",
                description=record.content,
                confidence=record.confidence,
                equipment_id=record.metadata.get("equipment_id") if record.metadata else None,
                zone_id=record.metadata.get("zone_id") if record.metadata else None,
                contractor_id=record.metadata.get("contractor_id") if record.metadata else None,
                evidence=record.metadata.get("evidence") if record.metadata else None,
                context_signature=record.metadata.get("context_signature") if record.metadata else None,
                tags=record.metadata.get("tags") if record.metadata else None,
            )
            if skills:
                return str(skills[0].skill_id)
            return ""
        except Exception as e:
            logger.error(f"[InstitutionalAdapter] write failed: {e}")
            return ""

    async def health(self) -> StoreHealth:
        return StoreHealth(
            tier=MemoryTier.T5_INSTITUTIONAL,
            healthy=self._skillbook is not None or self._scenario_retriever is not None,
        )
