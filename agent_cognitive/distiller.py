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

SWARM_NODES_FILE = os.path.join(os.path.dirname(__file__), "..", "agent_commercial", "swarm_nodes.py")

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

    def _inject_constraint_into_node_prompt(self, agent_name: str, constraint: str) -> bool:
        """
        Rewrites the swarm_nodes.py file to inject a hard constraint
        into the agent's system_prompt. This is the most aggressive form of learning.
        The constraint is appended to the agent's system_prompt string in-place.
        """
        if not os.path.exists(SWARM_NODES_FILE):
            logger.warning(f"[Distiller] swarm_nodes.py not found at {SWARM_NODES_FILE}. Skipping prompt injection.")
            return False

        with open(SWARM_NODES_FILE, "r", encoding="utf-8") as f:
            source = f.read()

        # Build the injection marker for this agent
        injection_marker = f"# [DISTILLED_RULE:{agent_name}]"
        
        # If already injected, skip to avoid duplicates
        if injection_marker in source:
            logger.info(f"[Distiller] Constraint already injected for {agent_name}. Skipping.")
            return False

        # Locate the agent's system_prompt definition and append the rule
        # We search for a pattern like: "agent_name" ... system_prompt = "..."
        # Practically, we search for the class name or label and inject after its system prompt assignment
        search_str = f'"{agent_name}"'
        insert_pos = source.find(search_str)
        if insert_pos == -1:
            logger.warning(f"[Distiller] Could not find {agent_name} definition in swarm_nodes.py. Skipping injection.")
            return False

        # Find the end of that agent block's first string/triple-quote
        prompt_marker = '"""'
        end_prompt_pos = source.find(prompt_marker, insert_pos + len(search_str) + 100)
        if end_prompt_pos == -1:
            logger.warning(f"[Distiller] Could not find system prompt end for {agent_name}. Skipping.")
            return False

        # Compose the insertion
        injection = f"\\n{injection_marker} DO NOT approve proposals that have historically led to safety vetoes: {constraint}"
        new_source = source[:end_prompt_pos] + injection + source[end_prompt_pos:]

        with open(SWARM_NODES_FILE, "w", encoding="utf-8") as f:
            f.write(new_source)

        logger.info(f"[Distiller] Injected constraint into {agent_name}'s system prompt in swarm_nodes.py.")
        return True

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
                
                # 2. Optionally inject into agent source prompts
                if inject_prompts:
                    for agent_name in agents:
                        constraint_text = f"Repeated vetoes on '{pattern_key}' (confidence={confidence:.1%})"
                        self._inject_constraint_into_node_prompt(agent_name, constraint_text)

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
