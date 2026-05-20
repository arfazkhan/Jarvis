"""
Knowledge Distiller
===================
Phase 4 SONA Feature: Self-Modifying Prompts via Knowledge Distillation.

The Distiller runs as an offline/nightly job. It:
1. Reads recent Swarm Trajectories from the BuildingSkillbook decisions table.
2. Clusters patterns (e.g. "Agent X vetoed Action Y 9 out of 10 times").
3. When a pattern hits a 0.9+ confidence threshold, it:
   a. Writes a new, permanent constraint into the Skillbook as a 'threshold' Skill.
   b. Rewrites the on-disk system_prompt of the relevant Swarm Node to hardcode the rule.
4. This ensures the Swarm never makes the same mistake twice, even across restarts.
"""

import json
import logging
import os
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional

logger = logging.getLogger("arvis.cognitive.distiller")

# Rules are now persisted to the distilled_rules DB table instead of rewriting source files.

CONFIDENCE_THRESHOLD = 0.88  # Must see a pattern in 88%+ cases to hardcode it


class KnowledgeDistiller:
    """
    Analyzes Swarm Trajectories to distill permanent knowledge rules
    and autonomously injects them into Swarm Node system prompts.
    """

    def __init__(self, building_id: str = "default"):
        self.building_id = building_id

    async def _get_recent_decisions(self, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """Pulls the latest decision trajectories from the BuildingSkillbook DB."""
        from agent_commercial.skillbook import get_skillbook
        skillbook = get_skillbook(self.building_id)
        await skillbook.ensure_initialized()
        decisions = await skillbook.get_recent_decisions(limit=500)
        cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()
        return [d for d in decisions if d.get("timestamp", "") >= cutoff]

    def _cluster_veto_patterns(self, decisions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Scans decisions for repeated VETO patterns.
        Returns a dict: { pattern_key -> { count, total, agents, last_seen } }
        """
        pattern_tally: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"vetoes": 0, "total": 0, "agents": set(), "last_seen": ""})

        for d in decisions:
            trajectory = d.get("trajectory") or {}
            action_map = trajectory.get("action", {})
            for agent_name, action_text in action_map.items():
                if isinstance(action_text, str) and "VOTE: VETO" in action_text:
                    # Extract proposer from context
                    pre_state = trajectory.get("pre_state", {})
                    query_snippet = str(pre_state.get("query", ""))[:50]
                    pattern_key = f"veto_{agent_name}"
                    pattern_tally[pattern_key]["vetoes"] += 1
                    pattern_tally[pattern_key]["agents"].add(agent_name)
                    pattern_tally[pattern_key]["last_seen"] = d.get("timestamp", "")

            # Track total attempts that were actionable
            chosen = d.get("chosen_action", "")
            if "Action" in chosen:
                # Rough grouping — we track all agents involved
                for agent_name in action_map.keys():
                    pattern_key = f"veto_{agent_name}"
                    pattern_tally[pattern_key]["total"] += 1

        return dict(pattern_tally)

    def _compute_confidence(self, pattern: Dict[str, Any]) -> float:
        """Veto rate confidence — how often this agent blocks an action."""
        total = max(1, pattern.get("total", 1))
        vetoes = pattern.get("vetoes", 0)
        return round(vetoes / total, 3)

    async def _write_skill_to_skillbook(self, pattern_key: str, confidence: float, agents: List[str]) -> None:
        """Writes a high-confidence learned constraint to the Skillbook as a 'threshold' Skill."""
        from agent_commercial.skillbook import get_skillbook, SkillType
        skillbook = get_skillbook(self.building_id)
        await skillbook.ensure_initialized()
        await skillbook.add_skill(
            skill_type=SkillType.THRESHOLD,
            title=f"[Distilled Rule] {pattern_key}",
            description=(
                f"Learned from {len(agents)} agent(s). Confidence: {confidence:.1%}. "
                f"Agents [{', '.join(agents)}] consistently VETO related proposals. "
                f"This rule was autonomously distilled by the KnowledgeDistiller."
            ),
            confidence=confidence,
            created_by="distiller"
        )
        logger.info(f"[Distiller] Wrote skill to Skillbook: {pattern_key} (confidence={confidence:.1%})")

    async def _persist_rule_to_db(self, agent_name: str, constraint: str, confidence: float) -> bool:
        """
        Persist a learned constraint to the distilled_rules DB table.
        Replaces the previous approach of rewriting swarm_nodes.py source code,
        which was fragile and unsafe in production.
        Rules are loaded at runtime by SwarmNode.process() before each ReAct turn.
        """
        try:
            import uuid as _uuid
            from agent_commercial.database import get_database
            db = get_database()
            rule_id = f"distilled_{agent_name}_{_uuid.uuid4().hex[:8]}"
            await db.save_distilled_rule({
                "rule_id": rule_id,
                "agent_name": agent_name,
                "rule_text": (
                    f"DO NOT approve proposals that have historically led to safety vetoes: "
                    f"{constraint} (confidence={confidence:.1%})"
                ),
                "confidence": confidence,
                "veto_count": 1,
                "active": 1,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            })
            logger.info(
                "[Distiller] Rule persisted to DB for %s (confidence=%.1f%%): %s",
                agent_name, confidence * 100, constraint[:80],
            )
            return True
        except Exception as exc:
            logger.warning("[Distiller] DB rule persistence failed: %s", exc)
            return False

    async def run_distillation(self, inject_prompts: bool = True) -> Dict[str, Any]:
        """
        Main distillation loop. Call this nightly from `CognitiveLoop`.
        Returns a summary of what patterns were learned and injected.
        """
        logger.info("[Distiller] Starting nightly knowledge distillation run...")
        decisions = await self._get_recent_decisions(lookback_days=30)
        
        if not decisions:
            logger.info("[Distiller] No recent decisions found. Nothing to distill.")
            return {"distilled": 0, "skipped": 0}

        patterns = self._cluster_veto_patterns(decisions)
        distilled = 0
        skipped = 0

        for pattern_key, pattern_data in patterns.items():
            confidence = self._compute_confidence(pattern_data)
            agents = list(pattern_data.get("agents", set()))
            
            if confidence >= CONFIDENCE_THRESHOLD:
                logger.info(f"[Distiller] HIGH CONFIDENCE pattern found: {pattern_key} ({confidence:.1%}). Distilling...")
                
                # 1. Write to Skillbook
                await self._write_skill_to_skillbook(pattern_key, confidence, agents)
                
                # 2. Persist learned constraints to DB (replaces source-code rewriting)
                if inject_prompts:
                    for agent_name in agents:
                        constraint_text = f"Repeated vetoes on '{pattern_key}'"
                        await self._persist_rule_to_db(agent_name, constraint_text, confidence)

                distilled += 1
            else:
                skipped += 1
        
        result = {
            "run_at": datetime.now().isoformat(),
            "decisions_analyzed": len(decisions),
            "patterns_found": len(patterns),
            "distilled": distilled,
            "skipped": skipped,
        }
        logger.info(f"[Distiller] Distillation complete: {result}")
        return result


async def run_distiller(building_id: str = "default") -> Dict[str, Any]:
    """Entrypoint for the distiller. Can be scheduled as a nightly cron."""
    distiller = KnowledgeDistiller(building_id=building_id)
    return await distiller.run_distillation()


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_distiller())
    print(json.dumps(result, indent=2))
