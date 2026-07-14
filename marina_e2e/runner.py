"""
Marina E2E v3 Runner — wraps existing marina_prove_it.py with agentic judge.

Usage:
    python -m marina_e2e.runner --phase S1_P2
    python -m marina_e2e.runner --full
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from marina_e2e.judge_agent import JudgeAgent
from marina_e2e.judge_tools import TOOL_REGISTRY
from marina_e2e.schemas import JudgmentEntry, PhaseWindow

logger = logging.getLogger("marina.runner")

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "agent_commercial" / "data" / "arvis_bms.db")


def get_plan_id_from_copilot(copilot) -> Optional[str]:
    """Extract the last investigation plan_id from copilot after a chat call."""
    plan = getattr(copilot.llm_agent, '_last_plan', None)
    if plan is None:
        return None
    return getattr(plan, 'id', None) or getattr(plan, 'plan_id', None)


class MarinaJudgeRunner:
    """
    Augments the existing Marina pipeline with the agentic judge.
    Wraps JudgePanel scoring with DB-introspecting JudgeAgent.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        budget_per_dim: int = 8,
    ):
        self.db_path = db_path
        self.run_id = str(uuid.uuid4())[:12]
        self.judge = JudgeAgent(
            db_path=db_path,
            budget_per_dim=budget_per_dim,
        )
        self.phase_windows: List[PhaseWindow] = []
        self.all_judgments: Dict[str, List[JudgmentEntry]] = {}
        self._current_phase_start: Optional[str] = None

    def begin_phase(self, phase: str, scenario: str, operator_id: str = "noor", building_id: str = "marina-heights"):
        """Mark start of a phase for time-windowed queries."""
        self._current_phase_start = datetime.now(timezone.utc).isoformat()
        self._current_phase = phase
        self._current_scenario = scenario
        self._current_operator = operator_id
        self._current_building = building_id
        self._phase_plan_ids: List[str] = []

    def record_plan_id(self, plan_id: Optional[str]):
        """Record a plan_id from a chat call during current phase."""
        if plan_id:
            self._phase_plan_ids.append(plan_id)

    def end_phase(self) -> PhaseWindow:
        """Mark end of phase, return the window."""
        t_end = datetime.now(timezone.utc).isoformat()
        window = PhaseWindow(
            phase=self._current_phase,
            scenario=self._current_scenario,
            t_start=self._current_phase_start or t_end,
            t_end=t_end,
            plan_ids=list(self._phase_plan_ids),
            operator_id=self._current_operator,
            building_id=self._current_building,
        )
        self.phase_windows.append(window)
        return window

    async def score_phase_with_introspection(
        self,
        dimensions: List[Dict[str, Any]],
        arvis_output: str,
        phase_context: str = "",
        deterministic_results: Optional[Dict[str, bool]] = None,
    ) -> List[JudgmentEntry]:
        """
        Score all dimensions using the agentic judge with DB introspection.
        Uses the most recent plan_id from the current phase.
        """
        plan_id = self._phase_plan_ids[-1] if self._phase_plan_ids else None
        window = PhaseWindow(
            phase=self._current_phase,
            scenario=self._current_scenario,
            t_start=self._current_phase_start or "",
            t_end=datetime.now(timezone.utc).isoformat(),
            plan_ids=self._phase_plan_ids,
            operator_id=self._current_operator,
            building_id=self._current_building,
        )

        entries = await self.judge.score_phase(
            dimensions=dimensions,
            arvis_output=arvis_output,
            plan_id=plan_id,
            phase_context=phase_context,
            phase_window=window,
            deterministic_results=deterministic_results,
        )

        self.all_judgments[self._current_phase] = entries
        return entries

    async def persist_judgments(self, phase: str):
        """Persist judgment entries to the judgment_ledger table."""
        entries = self.all_judgments.get(phase, [])
        if not entries:
            return

        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from agent_commercial.database import BMSDatabase
            db = BMSDatabase(self.db_path)

            for entry in entries:
                await db.save_judgment(
                    run_id=self.run_id,
                    phase=phase,
                    scenario=self._current_scenario,
                    dimension_id=entry.dimension_id,
                    score=entry.score,
                    reasoning=entry.reasoning,
                    evidence_chain=[e.__dict__ if hasattr(e, '__dict__') else e for e in entry.evidence_chain],
                    tool_calls_used=entry.tool_calls_used,
                    judge_model_id="moonshot.kimi-k2-thinking",
                    wall_time_ms=entry.wall_time_ms,
                )
            logger.info(f"[Runner] Persisted {len(entries)} judgments for {phase}")
        except Exception as e:
            logger.error(f"[Runner] Failed to persist judgments: {e}")

    def summary(self) -> Dict[str, Any]:
        """Produce run summary."""
        phase_summaries = {}
        for phase, entries in self.all_judgments.items():
            scored = [e for e in entries if not e.abstained]
            abstained = [e for e in entries if e.abstained]
            avg_score = sum(e.score for e in scored) / len(scored) if scored else 0.0
            phase_summaries[phase] = {
                "scored_count": len(scored),
                "abstained_count": len(abstained),
                "avg_score": round(avg_score, 2),
                "total_tool_calls": sum(e.tool_calls_used for e in entries),
            }
        return {
            "run_id": self.run_id,
            "phases": phase_summaries,
            "phase_windows": [
                {"phase": w.phase, "plan_ids": w.plan_ids, "t_start": w.t_start, "t_end": w.t_end}
                for w in self.phase_windows
            ],
        }


async def run_single_phase(phase: str = "S1_P2"):
    """Smoke test: run a single phase with the agentic judge."""
    runner = MarinaJudgeRunner()
    logger.info(f"[Marina E2E v3] Starting single phase: {phase}")
    logger.info(f"[Marina E2E v3] Run ID: {runner.run_id}")
    logger.info(f"[Marina E2E v3] Available tools: {list(TOOL_REGISTRY.keys())}")
    logger.info(f"[Marina E2E v3] DB path: {runner.db_path}")
    print(json.dumps(runner.summary(), indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Marina E2E v3 Runner")
    parser.add_argument("--phase", default="S1_P2", help="Phase to run (default: S1_P2)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    asyncio.run(run_single_phase(args.phase))
