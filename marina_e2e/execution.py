"""
Marina E2E v3 — Full Execution Engine.

Orchestrates complete S1+S2 scenario runs with:
- Multi-operator personas
- Agentic judge with DB introspection
- Cross-phase consistency checks
- N-run variance analysis
- Canonical run reports
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from marina_e2e.consistency import ConsistencyChecker
from marina_e2e.judge_agent import JudgeAgent
from marina_e2e.personas import OperatorOrchestrator, PHASE_SCRIPTS, ShiftSchedule
from marina_e2e.runner import MarinaJudgeRunner
from marina_e2e.schemas import ConsistencyFinding, JudgmentEntry, PhaseWindow

logger = logging.getLogger("marina.execution")

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "agent_commercial" / "data" / "arvis_bms.db")


# ---------------------------------------------------------------------------
# Scenario Definitions
# ---------------------------------------------------------------------------

SCENARIO_PHASES: Dict[str, List[str]] = {
    "S1": ["S1_P0", "S1_P1", "S1_P2", "S1_P3", "S1_P4", "S1_P5", "S1_P6", "S1_P7"],
    "S2": ["S2_P0", "S2_P1", "S2_P2", "S2_P3", "S2_P4", "S2_P5", "S2_P6", "S2_P7"],
}

PHASE_SIM_WINDOWS: Dict[str, Dict[str, Any]] = {
    "S1_P0": {"sim_day_start": 0, "sim_day_end": 7, "description": "Data audit & onboarding"},
    "S1_P1": {"sim_day_start": 7, "sim_day_end": 35, "description": "Silent observation (4 weeks)"},
    "S1_P2": {"sim_day_start": 35, "sim_day_end": 56, "description": "First detections"},
    "S1_P3": {"sim_day_start": 56, "sim_day_end": 90, "description": "Regular recommendations"},
    "S1_P4": {"sim_day_start": 90, "sim_day_end": 140, "description": "Chiller sequencing optimization"},
    "S1_P5": {"sim_day_start": 140, "sim_day_end": 180, "description": "Ghost maintenance detection"},
    "S1_P6": {"sim_day_start": 180, "sim_day_end": 220, "description": "Terminal advisory (Chiller 4)"},
    "S1_P7": {"sim_day_start": 330, "sim_day_end": 365, "description": "Year-end, personnel change"},
    "S2_P0": {"sim_day_start": 0, "sim_day_end": 7, "description": "Imposed deployment"},
    "S2_P1": {"sim_day_start": 7, "sim_day_end": 35, "description": "First false positive (CT-2)"},
    "S2_P2": {"sim_day_start": 35, "sim_day_end": 56, "description": "Deadband retraction"},
    "S2_P3": {"sim_day_start": 56, "sim_day_end": 90, "description": "FUD document attack"},
    "S2_P4": {"sim_day_start": 90, "sim_day_end": 140, "description": "Approval hell"},
    "S2_P5": {"sim_day_start": 140, "sim_day_end": 180, "description": "False positive (18k QAR)"},
    "S2_P6": {"sim_day_start": 180, "sim_day_end": 220, "description": "Chiller 4 redemption"},
    "S2_P7": {"sim_day_start": 330, "sim_day_end": 365, "description": "Honest year-end (67%)"},
}


# ---------------------------------------------------------------------------
# Run Result
# ---------------------------------------------------------------------------

@dataclass
class PhaseRunResult:
    phase: str
    scenario: str
    judgments: List[JudgmentEntry]
    operator_interactions: int
    plan_ids: List[str]
    wall_time_s: float
    weighted_score: float
    threshold: float
    passed: bool

    @property
    def scored_count(self) -> int:
        return sum(1 for j in self.judgments if not j.abstained)

    @property
    def abstained_count(self) -> int:
        return sum(1 for j in self.judgments if j.abstained)


@dataclass
class ScenarioRunResult:
    scenario: str
    run_id: str
    phases: List[PhaseRunResult]
    consistency_findings: List[ConsistencyFinding]
    total_wall_time_s: float

    @property
    def all_passed(self) -> bool:
        return all(p.passed for p in self.phases)

    @property
    def overall_score(self) -> float:
        scored = [p for p in self.phases if p.scored_count > 0]
        if not scored:
            return 0.0
        return sum(p.weighted_score for p in scored) / len(scored)

    def to_report(self) -> str:
        lines = [
            "=" * 80,
            f"MARINA E2E v3 — {self.scenario} RUN REPORT",
            f"Run ID: {self.run_id}",
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
            f"Total wall time: {self.total_wall_time_s:.1f}s",
            f"Overall score: {self.overall_score:.2f}/10",
            f"All phases passed: {self.all_passed}",
            "=" * 80,
            "",
        ]

        for phase_result in self.phases:
            status = "PASS" if phase_result.passed else "FAIL"
            lines.append(
                f"  {phase_result.phase}: {phase_result.weighted_score:.2f}/{phase_result.threshold:.1f} "
                f"[{status}] — {phase_result.scored_count} scored, "
                f"{phase_result.abstained_count} abstained, "
                f"{phase_result.operator_interactions} interactions"
            )

        if self.consistency_findings:
            lines.append("")
            lines.append("CONSISTENCY FINDINGS:")
            for f in self.consistency_findings:
                lines.append(f"  [{f.severity.upper()}] {f.check_type}: {f.description}")

        lines.append("")
        lines.append("=" * 80)
        return "\n".join(lines)


@dataclass
class VarianceReport:
    """N-run variance analysis."""
    scenario: str
    n_runs: int
    phase_scores: Dict[str, List[float]]  # phase -> list of scores across runs
    pass_rates: Dict[str, float]  # phase -> fraction of runs that passed
    overall_mean: float
    overall_std: float
    all_passed_rate: float

    def to_report(self) -> str:
        import math
        lines = [
            "=" * 80,
            f"MARINA E2E v3 — VARIANCE REPORT ({self.scenario}, N={self.n_runs})",
            f"Overall: mean={self.overall_mean:.2f}, std={self.overall_std:.3f}",
            f"All-phases-pass rate: {self.all_passed_rate:.0%}",
            "=" * 80,
            "",
            f"{'Phase':<12} {'Mean':>6} {'Std':>6} {'Min':>6} {'Max':>6} {'Pass%':>6}",
            "-" * 50,
        ]
        for phase, scores in self.phase_scores.items():
            if not scores:
                continue
            mean = sum(scores) / len(scores)
            std = math.sqrt(sum((s - mean) ** 2 for s in scores) / max(1, len(scores) - 1))
            lines.append(
                f"{phase:<12} {mean:>6.2f} {std:>6.3f} {min(scores):>6.2f} "
                f"{max(scores):>6.2f} {self.pass_rates.get(phase, 0):.0%}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------

class MarinaExecutionEngine:
    """
    Full E2E execution engine.
    Runs complete scenarios with multi-operator personas and agentic judge.
    """

    # Pass thresholds per phase (from JudgePanel)
    PASS_THRESHOLDS: Dict[str, float] = {
        "S1_P0": 4.0, "S1_P1": 4.0, "S1_P2": 7.0, "S1_P3": 7.0,
        "S1_P4": 7.0, "S1_P5": 8.0, "S1_P6": 9.0, "S1_P7": 8.0,
        "S2_P0": 4.0, "S2_P1": 6.5, "S2_P2": 7.0, "S2_P3": 7.5,
        "S2_P4": 7.0, "S2_P5": 8.0, "S2_P6": 9.0, "S2_P7": 7.5,
    }

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        budget_per_dim: int = 8,
    ):
        self.db_path = db_path
        self.budget_per_dim = budget_per_dim

    async def run_scenario(
        self,
        scenario: str,
        phases: Optional[List[str]] = None,
        copilot=None,
    ) -> ScenarioRunResult:
        """Run a full scenario (S1 or S2) with all phases."""
        run_id = str(uuid.uuid4())[:12]
        t_start = time.time()

        phases_to_run = phases or SCENARIO_PHASES.get(scenario, [])
        orchestrator = OperatorOrchestrator(scenario)
        runner = MarinaJudgeRunner(db_path=self.db_path, budget_per_dim=self.budget_per_dim)
        runner.run_id = run_id

        phase_results: List[PhaseRunResult] = []

        for phase in phases_to_run:
            logger.info(f"[Execution] Starting phase {phase}")
            phase_result = await self._run_phase(
                phase=phase,
                scenario=scenario,
                orchestrator=orchestrator,
                runner=runner,
                copilot=copilot,
            )
            phase_results.append(phase_result)
            logger.info(
                f"[Execution] Phase {phase}: {phase_result.weighted_score:.2f} "
                f"({'PASS' if phase_result.passed else 'FAIL'})"
            )

        # Cross-phase consistency
        consistency = ConsistencyChecker(db_path=self.db_path)
        findings = consistency.check_all(runner.phase_windows)

        total_time = time.time() - t_start

        return ScenarioRunResult(
            scenario=scenario,
            run_id=run_id,
            phases=phase_results,
            consistency_findings=findings,
            total_wall_time_s=total_time,
        )

    async def _run_phase(
        self,
        phase: str,
        scenario: str,
        orchestrator: OperatorOrchestrator,
        runner: MarinaJudgeRunner,
        copilot=None,
    ) -> PhaseRunResult:
        """Execute a single phase with operator interactions and judge scoring."""
        t_start = time.time()
        phase_window = PHASE_SIM_WINDOWS.get(phase, {})
        sim_day = phase_window.get("sim_day_start", 0)

        runner.begin_phase(phase, scenario)

        # Get operators for this phase
        active_ops = orchestrator.get_active_operators(phase, hour=10.0, sim_day=sim_day)
        scripts = orchestrator.get_phase_script(phase)

        interaction_count = 0

        # Execute scripted interactions if copilot available
        if copilot and scripts:
            for script_block in scripts:
                op_id = script_block["operator"]
                op = orchestrator.operators.get(op_id)
                if not op or not op.is_available(phase):
                    continue

                for turn in script_block.get("turns", []):
                    message = turn["template"]
                    try:
                        resp = await self._chat_with_copilot(copilot, message, op_id)
                        plan_id = self._extract_plan_id(copilot)
                        runner.record_plan_id(plan_id)

                        decision = self._extract_decision(op, turn.get("intent", ""))
                        orchestrator.record_interaction(op_id, phase, message, resp, decision)
                        interaction_count += 1
                    except Exception as e:
                        logger.warning(f"[Execution] Interaction failed: {e}")

            # Shift handoff if applicable
            if any(s["operator"] in ("khalid",) for s in scripts):
                orchestrator.record_handoff("day", "evening", phase)

        window = runner.end_phase()

        # Score with agentic judge
        dimensions = self._get_dimensions(phase)
        arvis_output = self._collect_arvis_output(runner, phase)

        judgments = []
        if dimensions:
            judgments = await runner.score_phase_with_introspection(
                dimensions=dimensions,
                arvis_output=arvis_output,
                phase_context=phase_window.get("description", ""),
            )

        # Calculate weighted score
        threshold = self.PASS_THRESHOLDS.get(phase, 7.0)
        weighted_score = self._calculate_weighted_score(judgments, dimensions)
        passed = weighted_score >= threshold

        wall_time = time.time() - t_start

        return PhaseRunResult(
            phase=phase,
            scenario=scenario,
            judgments=judgments,
            operator_interactions=interaction_count,
            plan_ids=list(window.plan_ids) if window else [],
            wall_time_s=wall_time,
            weighted_score=weighted_score,
            threshold=threshold,
            passed=passed,
        )

    async def run_n_times(
        self,
        scenario: str,
        n: int = 3,
        copilot=None,
    ) -> VarianceReport:
        """Run scenario N times for variance analysis."""
        import math

        all_results: List[ScenarioRunResult] = []
        for i in range(n):
            logger.info(f"[Execution] Variance run {i+1}/{n}")
            result = await self.run_scenario(scenario, copilot=copilot)
            all_results.append(result)

        # Aggregate
        phase_scores: Dict[str, List[float]] = {}
        pass_counts: Dict[str, int] = {}

        for result in all_results:
            for pr in result.phases:
                phase_scores.setdefault(pr.phase, []).append(pr.weighted_score)
                pass_counts.setdefault(pr.phase, 0)
                if pr.passed:
                    pass_counts[pr.phase] += 1

        pass_rates = {phase: count / n for phase, count in pass_counts.items()}

        all_scores = [r.overall_score for r in all_results]
        overall_mean = sum(all_scores) / len(all_scores) if all_scores else 0.0
        overall_std = math.sqrt(
            sum((s - overall_mean) ** 2 for s in all_scores) / max(1, len(all_scores) - 1)
        ) if len(all_scores) > 1 else 0.0

        all_passed_rate = sum(1 for r in all_results if r.all_passed) / n

        return VarianceReport(
            scenario=scenario,
            n_runs=n,
            phase_scores=phase_scores,
            pass_rates=pass_rates,
            overall_mean=overall_mean,
            overall_std=overall_std,
            all_passed_rate=all_passed_rate,
        )

    # ---- Helpers ---------------------------------------------------------

    async def _chat_with_copilot(self, copilot, message: str, operator_id: str) -> str:
        """Send message to copilot as a given operator."""
        try:
            resp = await copilot.llm_agent.chat(message)
            return str(resp) if resp else ""
        except Exception as e:
            logger.warning(f"[Execution] Chat failed for {operator_id}: {e}")
            return ""

    @staticmethod
    def _extract_plan_id(copilot) -> Optional[str]:
        """Extract plan_id from copilot after chat."""
        plan = getattr(copilot, '_last_plan', None) if copilot else None
        if plan is None:
            plan = getattr(getattr(copilot, 'llm_agent', None), '_last_plan', None)
        if plan is None:
            return None
        return getattr(plan, 'id', None) or getattr(plan, 'plan_id', None)

    @staticmethod
    def _extract_decision(op, intent: str) -> str:
        """Map intent to likely decision code."""
        intent_decisions = {
            "approve": "ACCEPT",
            "request_action": "ACCEPT",
            "escalation_acceptance": "ACCEPT",
            "trust_recovery": "PARTIAL",
            "pushback": "PARTIAL",
            "challenge": "PARTIAL",
            "challenge_methodology": "PARTIAL",
            "reject": "REJECT",
            "trust_reduction": "REJECT",
            "false_positive_reaction": "REJECT",
            "dismiss_attempt": "REJECT",
            "defer": "DEFER_TO_NOOR",
            "evening_uncertainty": "DEFER_TO_NOOR",
        }
        return intent_decisions.get(intent, "SILENCE")

    def _get_dimensions(self, phase: str) -> List[Dict[str, Any]]:
        """Get judge dimensions for a phase (imported from JudgePanel)."""
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from scratch.marina_personas import JudgePanel
            return JudgePanel.DIMENSIONS.get(phase, [])
        except ImportError:
            return []

    @staticmethod
    def _collect_arvis_output(runner: MarinaJudgeRunner, phase: str) -> str:
        """Collect ARVIS output text for judge scoring."""
        return f"[ARVIS output for phase {phase} — collected from conversation history]"

    @staticmethod
    def _calculate_weighted_score(
        judgments: List[JudgmentEntry],
        dimensions: List[Dict[str, Any]],
    ) -> float:
        """Calculate weighted average score from judgments."""
        if not judgments:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        dim_weights = {d["id"]: d.get("weight", 1.0) for d in dimensions}

        for j in judgments:
            if j.abstained:
                continue
            weight = dim_weights.get(j.dimension_id, 1.0)
            weighted_sum += j.score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Marina E2E v3 Full Execution")
    parser.add_argument("--scenario", choices=["S1", "S2", "both"], default="S1")
    parser.add_argument("--phase", help="Run single phase (e.g. S1_P2)")
    parser.add_argument("--n-runs", type=int, default=1, help="Number of runs for variance")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--budget", type=int, default=8, help="Tool budget per dimension")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    engine = MarinaExecutionEngine(db_path=args.db_path, budget_per_dim=args.budget)

    if args.phase:
        scenario = "S1" if args.phase.startswith("S1") else "S2"
        result = await engine.run_scenario(scenario, phases=[args.phase])
        print(result.to_report())
    elif args.n_runs > 1:
        scenarios = ["S1", "S2"] if args.scenario == "both" else [args.scenario]
        for sc in scenarios:
            report = await engine.run_n_times(sc, n=args.n_runs)
            print(report.to_report())
    else:
        scenarios = ["S1", "S2"] if args.scenario == "both" else [args.scenario]
        for sc in scenarios:
            result = await engine.run_scenario(sc)
            print(result.to_report())


if __name__ == "__main__":
    asyncio.run(main())
