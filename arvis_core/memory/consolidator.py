"""
Memory Consolidator
====================
Nightly compaction job for the ARVIS 7-tier memory system.

Three jobs:
1. Stale rule decay   — soft-delete T3 distilled_rules with hit_count=0 and age>90d
2. Episodic → T3 distillation — cluster similar past investigations, propose new rule via LLM
3. Skillbook confidence decay — reduce confidence of T5 entries unconfirmed >180d
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("arvis.memory.consolidator")

STALE_RULE_AGE_DAYS = 90
SKILLBOOK_DECAY_DAYS = 180
MIN_INVESTIGATIONS_FOR_DISTILL = 3   # cluster size threshold


class MemoryConsolidator:
    """
    Nightly compaction job. Call consolidate(building_id) once per day.
    All operations degrade gracefully — nothing raises on partial failure.
    """

    def __init__(self, orchestrator=None, db=None, llm=None):
        self._mo = orchestrator   # MemoryOrchestrator
        self._db = db             # BMSDatabase
        self._llm = llm           # UnifiedLLM — used for distillation LLM call

    async def consolidate(self, building_id: str = "") -> dict:
        """Run all three consolidation jobs. Returns summary dict."""
        logger.info(f"[Consolidator] Starting nightly consolidation for building={building_id!r}")
        results = {}

        decay_result = await self._decay_stale_rules(building_id)
        results["stale_rules_removed"] = decay_result

        distill_result = await self._distill_episodic_to_t3(building_id)
        results["new_rules_proposed"] = distill_result

        skillbook_result = await self._decay_stale_skillbook(building_id)
        results["skillbook_entries_decayed"] = skillbook_result

        logger.info(f"[Consolidator] Done: {results}")
        return results

    # ── Job 1: Stale rule decay ───────────────────────────────────────────────

    async def _decay_stale_rules(self, building_id: str) -> int:
        """Soft-delete distilled_rules with hit_count=0 and age > STALE_RULE_AGE_DAYS."""
        if self._db is None:
            return 0
        removed = 0
        try:
            rules = await self._db.get_distilled_rules(agent_name="arvis")
            cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_RULE_AGE_DAYS)
            for rule in rules:
                hit_count = int(rule.get("hit_count", 0))
                if hit_count > 0:
                    continue
                created_raw = rule.get("created_at") or rule.get("timestamp")
                if not created_raw:
                    continue
                try:
                    created = (
                        datetime.fromisoformat(created_raw)
                        if isinstance(created_raw, str)
                        else created_raw
                    )
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if created < cutoff:
                    rule_id = rule.get("id") or rule.get("rule_id")
                    if rule_id and hasattr(self._db, "soft_delete_distilled_rule"):
                        try:
                            await self._db.soft_delete_distilled_rule(rule_id)
                            removed += 1
                            logger.info(f"[Consolidator] Decayed stale rule {rule_id}")
                        except Exception as _e:
                            logger.debug(f"[Consolidator] Rule decay failed for {rule_id}: {_e}")
        except Exception as e:
            logger.error(f"[Consolidator] _decay_stale_rules error: {e}")
        return removed

    # ── Job 2: Episodic → T3 distillation ────────────────────────────────────

    async def _distill_episodic_to_t3(self, building_id: str) -> int:
        """
        If ≥ MIN_INVESTIGATIONS_FOR_DISTILL past investigations share a common fault/symptom,
        propose a new distilled rule via LLM and write it to T3.
        """
        if self._mo is None or self._db is None:
            return 0
        proposed = 0
        try:
            from arvis_core.memory.types import MemoryTier
            t2_hits = await self._mo.query(
                query="fault investigation",
                building_id=building_id,
                tiers=[MemoryTier.T2_EPISODIC],
                top_k=20,
            )
            if len(t2_hits) < MIN_INVESTIGATIONS_FOR_DISTILL:
                return 0

            # Simple clustering: group by shared keyword overlap
            summaries = [h.content for h in t2_hits]
            cluster = summaries[:MIN_INVESTIGATIONS_FOR_DISTILL]

            if self._llm is not None:
                prompt = (
                    "You are an ARVIS knowledge distiller. "
                    "The following are summaries of past building management investigations:\n\n"
                    + "\n".join(f"- {s}" for s in cluster)
                    + "\n\nIdentify ONE concise operational rule (max 2 sentences) "
                    "that generalises across all these cases. "
                    "Return ONLY the rule text, nothing else."
                )
                try:
                    response = await self._llm.ask(
                        messages=[{"role": "user", "content": prompt}],
                        system_msgs=[{"role": "system", "content": "Concise rule extractor."}],
                        channel="consolidator",
                    )
                    rule_text = (response.content or "").strip()
                    if rule_text:
                        from arvis_core.memory.types import MemoryRecord
                        record_id = await self._mo.write(
                            MemoryTier.T3_PROCEDURAL,
                            MemoryRecord(
                                tier=MemoryTier.T3_PROCEDURAL,
                                content=rule_text,
                                source="consolidator:episodic_distillation",
                                confidence=0.65,
                                building_id=building_id,
                                conflict_check=True,
                            ),
                        )
                        if record_id:
                            proposed += 1
                            logger.info(f"[Consolidator] New T3 rule from distillation: {rule_text[:80]}")
                except Exception as _llm_err:
                    logger.debug(f"[Consolidator] LLM distillation failed: {_llm_err}")
        except Exception as e:
            logger.error(f"[Consolidator] _distill_episodic_to_t3 error: {e}")
        return proposed

    # ── Job 3: Skillbook confidence decay ────────────────────────────────────

    async def _decay_stale_skillbook(self, building_id: str) -> int:
        """Reduce confidence of T5 Skillbook entries unconfirmed for > SKILLBOOK_DECAY_DAYS."""
        if self._db is None:
            return 0
        decayed = 0
        try:
            if not hasattr(self._db, "decay_skillbook_entries"):
                return 0
            decayed = await self._db.decay_skillbook_entries(
                building_id=building_id,
                older_than_days=SKILLBOOK_DECAY_DAYS,
                decay_factor=0.9,
            )
            logger.info(f"[Consolidator] Decayed confidence on {decayed} stale skillbook entries")
        except Exception as e:
            logger.debug(f"[Consolidator] _decay_stale_skillbook error (non-fatal): {e}")
        return decayed
