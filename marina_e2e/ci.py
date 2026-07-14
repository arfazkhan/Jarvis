"""
Marina E2E v3 — CI Integration & Tooling.

Provides:
- `marina test` CLI command (smoke vs full modes)
- CI pipeline hook (exit codes, structured output)
- Judgment ledger viewer
- Run replay from persisted state
- Triage docs generation
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("marina.ci")

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "agent_commercial" / "data" / "arvis_bms.db")


# ---------------------------------------------------------------------------
# Test Modes
# ---------------------------------------------------------------------------

class TestMode:
    SMOKE = "smoke"       # ~30s, no LLM calls, deterministic gates only
    STANDARD = "standard"  # ~5min, single scenario, judge enabled
    FULL = "full"          # ~30min, both scenarios, N=3, consistency checks


# ---------------------------------------------------------------------------
# CI Runner
# ---------------------------------------------------------------------------

class CIRunner:
    """
    CI-friendly runner with structured output and exit codes.

    Exit codes:
        0: All tests pass
        1: One or more phases failed
        2: Infrastructure/config error
        3: Budget exceeded (too many LLM calls)
    """

    def __init__(
        self,
        mode: str = TestMode.STANDARD,
        db_path: str = DEFAULT_DB_PATH,
        output_format: str = "text",  # text, json, junit
        output_path: Optional[str] = None,
    ):
        self.mode = mode
        self.db_path = db_path
        self.output_format = output_format
        self.output_path = output_path
        self._results: Dict[str, Any] = {}

    async def run(self) -> int:
        """Execute tests and return exit code."""
        t_start = time.time()

        try:
            if self.mode == TestMode.SMOKE:
                exit_code = await self._run_smoke()
            elif self.mode == TestMode.STANDARD:
                exit_code = await self._run_standard()
            elif self.mode == TestMode.FULL:
                exit_code = await self._run_full()
            else:
                logger.error(f"Unknown test mode: {self.mode}")
                return 2
        except Exception as e:
            logger.error(f"[CI] Infrastructure error: {e}")
            self._results = {"error": str(e), "mode": self.mode}
            exit_code = 2

        self._results["wall_time_s"] = round(time.time() - t_start, 2)
        self._results["mode"] = self.mode
        self._results["exit_code"] = exit_code
        self._results["timestamp"] = datetime.now(timezone.utc).isoformat()

        self._emit_output()
        return exit_code

    async def _run_smoke(self) -> int:
        """Smoke test: verify infrastructure, no LLM calls."""
        findings: List[str] = []

        # 1. Check DB exists and has required tables
        db_ok, db_msg = self._check_db()
        if not db_ok:
            findings.append(f"DB check failed: {db_msg}")

        # 2. Check judge tools importable
        try:
            from marina_e2e.judge_tools import TOOL_REGISTRY, get_all_tools
            tools = get_all_tools()
            if len(tools) < 9:
                findings.append(f"Only {len(tools)} tools registered, expected >= 9")
        except ImportError as e:
            findings.append(f"Import failed: {e}")

        # 3. Check physics engine
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from scratch.marina_physics import create_marina
            b = create_marina()
            snap = b.snapshot(sim_day=0, hour=14)
            if "WEATHER/OAT" not in snap:
                findings.append("Physics snapshot missing WEATHER/OAT")
            if "TARIFF/BUCKET" not in snap:
                findings.append("Physics snapshot missing TARIFF/BUCKET")
        except Exception as e:
            findings.append(f"Physics engine error: {e}")

        # 4. Check schemas
        try:
            from marina_e2e.schemas import JudgmentEntry, PhaseWindow, ToolResult
        except ImportError as e:
            findings.append(f"Schema import failed: {e}")

        # 5. Check personas
        try:
            from marina_e2e.personas import OperatorOrchestrator, PERSONA_REGISTRY
            if len(PERSONA_REGISTRY) < 4:
                findings.append(f"Only {len(PERSONA_REGISTRY)} personas, expected 4")
        except ImportError as e:
            findings.append(f"Personas import failed: {e}")

        self._results = {
            "checks_run": 5,
            "findings": findings,
            "passed": len(findings) == 0,
        }

        return 0 if not findings else 1

    async def _run_standard(self) -> int:
        """Standard test: single scenario S1 with judge."""
        from marina_e2e.execution import MarinaExecutionEngine

        engine = MarinaExecutionEngine(db_path=self.db_path)
        result = await engine.run_scenario("S1")

        self._results = {
            "scenario": "S1",
            "overall_score": round(result.overall_score, 2),
            "all_passed": result.all_passed,
            "phases": [
                {
                    "phase": pr.phase,
                    "score": round(pr.weighted_score, 2),
                    "threshold": pr.threshold,
                    "passed": pr.passed,
                    "scored": pr.scored_count,
                    "abstained": pr.abstained_count,
                }
                for pr in result.phases
            ],
            "consistency_findings": len(result.consistency_findings),
        }

        return 0 if result.all_passed else 1

    async def _run_full(self) -> int:
        """Full test: both scenarios, N=3, consistency."""
        from marina_e2e.execution import MarinaExecutionEngine

        engine = MarinaExecutionEngine(db_path=self.db_path)

        s1_report = await engine.run_n_times("S1", n=3)
        s2_report = await engine.run_n_times("S2", n=3)

        s1_ok = s1_report.all_passed_rate >= 0.67  # 2/3 runs pass
        s2_ok = s2_report.all_passed_rate >= 0.67

        self._results = {
            "S1": {
                "mean_score": round(s1_report.overall_mean, 2),
                "std": round(s1_report.overall_std, 3),
                "pass_rate": round(s1_report.all_passed_rate, 2),
                "verdict": "PASS" if s1_ok else "FAIL",
            },
            "S2": {
                "mean_score": round(s2_report.overall_mean, 2),
                "std": round(s2_report.overall_std, 3),
                "pass_rate": round(s2_report.all_passed_rate, 2),
                "verdict": "PASS" if s2_ok else "FAIL",
            },
        }

        return 0 if (s1_ok and s2_ok) else 1

    def _check_db(self) -> tuple:
        """Verify database structure."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            # Core tables (must exist)
            required_tables = [
                "investigation_plans", "plan_evidence", "bft_votes",
                "violation_ledger", "llm_usage",
            ]
            # Optional tables (created by subsystems on first use)
            optional_tables = ["skills", "judgment_ledger", "distilled_rules"]
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing = {row[0] for row in cur.fetchall()}
            missing = [t for t in required_tables if t not in existing]
            conn.close()
            if missing:
                return False, f"Missing tables: {missing}"
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def _emit_output(self) -> None:
        """Write results in requested format."""
        if self.output_format == "json":
            output = json.dumps(self._results, indent=2)
        elif self.output_format == "junit":
            output = self._to_junit_xml()
        else:
            output = self._to_text()

        if self.output_path:
            Path(self.output_path).write_text(output, encoding="utf-8")
            logger.info(f"[CI] Results written to {self.output_path}")
        else:
            print(output)

    def _to_text(self) -> str:
        lines = ["=" * 60, "MARINA E2E — CI RESULTS", "=" * 60]
        lines.append(f"Mode: {self._results.get('mode', '?')}")
        lines.append(f"Exit code: {self._results.get('exit_code', '?')}")
        lines.append(f"Wall time: {self._results.get('wall_time_s', 0):.1f}s")
        lines.append("")

        if "findings" in self._results:
            if self._results["findings"]:
                lines.append("FINDINGS:")
                for f in self._results["findings"]:
                    lines.append(f"  - {f}")
            else:
                lines.append("All smoke checks passed.")

        if "phases" in self._results:
            lines.append(f"Overall score: {self._results.get('overall_score', 0)}")
            lines.append("")
            for p in self._results["phases"]:
                status = "PASS" if p["passed"] else "FAIL"
                lines.append(f"  {p['phase']}: {p['score']:.2f}/{p['threshold']} [{status}]")

        if "S1" in self._results and "S2" in self._results:
            for sc in ("S1", "S2"):
                d = self._results[sc]
                lines.append(f"  {sc}: mean={d['mean_score']}, std={d['std']}, "
                             f"pass_rate={d['pass_rate']:.0%} [{d['verdict']}]")

        lines.append("")
        return "\n".join(lines)

    def _to_junit_xml(self) -> str:
        """JUnit XML for CI systems (GitHub Actions, Jenkins, etc.)."""
        phases = self._results.get("phases", [])
        n_tests = len(phases) if phases else 1
        n_failures = sum(1 for p in phases if not p.get("passed", True))
        time_s = self._results.get("wall_time_s", 0)

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<testsuite name="marina-e2e" tests="{n_tests}" '
            f'failures="{n_failures}" time="{time_s}">',
        ]

        for p in phases:
            status = "passed" if p["passed"] else "failed"
            lines.append(
                f'  <testcase name="{p["phase"]}" time="0">'
            )
            if not p["passed"]:
                lines.append(
                    f'    <failure message="Score {p["score"]:.2f} below threshold {p["threshold"]}"/>'
                )
            lines.append('  </testcase>')

        if not phases:
            passed = self._results.get("passed", True)
            lines.append(f'  <testcase name="smoke" time="{time_s}">')
            if not passed:
                findings = self._results.get("findings", [])
                lines.append(f'    <failure message="{"; ".join(findings)}"/>')
            lines.append('  </testcase>')

        lines.append('</testsuite>')
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Judgment Ledger Viewer
# ---------------------------------------------------------------------------

class JudgmentLedgerViewer:
    """Read-only viewer for persisted judgment entries."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    def list_runs(self, limit: int = 20) -> List[dict]:
        """List recent run IDs with summary stats."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, COUNT(*) as n_judgments, "
                "AVG(score) as avg_score, MIN(timestamp) as started, "
                "MAX(timestamp) as ended "
                "FROM judgment_ledger GROUP BY run_id "
                "ORDER BY started DESC LIMIT ?",
                (limit,),
            )
            runs = [dict(row) for row in cur.fetchall()]
            conn.close()
            return runs
        except Exception:
            return []

    def get_run(self, run_id: str) -> List[dict]:
        """Get all judgments for a specific run."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM judgment_ledger WHERE run_id = ? ORDER BY timestamp",
                (run_id,),
            )
            entries = [dict(row) for row in cur.fetchall()]
            conn.close()
            return entries
        except Exception:
            return []

    def get_phase(self, run_id: str, phase: str) -> List[dict]:
        """Get judgments for a specific phase in a run."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM judgment_ledger WHERE run_id = ? AND phase = ? ORDER BY timestamp",
                (run_id, phase),
            )
            entries = [dict(row) for row in cur.fetchall()]
            conn.close()
            return entries
        except Exception:
            return []

    def format_entry(self, entry: dict) -> str:
        """Pretty-format a single judgment entry."""
        lines = [
            f"Dimension: {entry.get('dimension_id', '?')}",
            f"Score: {entry.get('score', 0):.1f}/10",
            f"Reasoning: {entry.get('reasoning', 'N/A')[:200]}",
            f"Tool calls: {entry.get('tool_calls_used', 0)}",
            f"Model: {entry.get('judge_model_id', '?')}",
        ]
        evidence = entry.get("evidence_chain")
        if evidence:
            try:
                chain = json.loads(evidence) if isinstance(evidence, str) else evidence
                lines.append(f"Evidence chain ({len(chain)} items):")
                for item in chain[:3]:
                    tool = item.get("tool", "?")
                    finding = item.get("finding", item.get("result_summary", ""))[:80]
                    lines.append(f"  - {tool}: {finding}")
            except (json.JSONDecodeError, TypeError):
                pass
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Replay Engine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """
    Replay a previous run's judge queries against current DB state.
    Detects if DB has changed in ways that would affect scores.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.viewer = JudgmentLedgerViewer(db_path)

    async def replay_run(self, run_id: str) -> dict:
        """Replay all tool queries from a previous run, compare results."""
        from marina_e2e.judge_tools import call_tool

        entries = self.viewer.get_run(run_id)
        if not entries:
            return {"error": f"No entries found for run {run_id}"}

        diffs: List[dict] = []
        for entry in entries:
            evidence_chain = entry.get("evidence_chain")
            if not evidence_chain:
                continue

            try:
                chain = json.loads(evidence_chain) if isinstance(evidence_chain, str) else evidence_chain
            except (json.JSONDecodeError, TypeError):
                continue

            for item in chain:
                tool_name = item.get("tool", "")
                params = item.get("params", {})
                original_summary = item.get("result_summary", "")

                # Re-run the tool
                result = call_tool(tool_name, db_path=self.db_path, **params)
                current_summary = str(result.data)[:200] if result.ok else result.error

                if current_summary != original_summary:
                    diffs.append({
                        "dimension": entry.get("dimension_id"),
                        "tool": tool_name,
                        "original": original_summary[:100],
                        "current": current_summary[:100],
                    })

        return {
            "run_id": run_id,
            "entries_checked": len(entries),
            "diffs_found": len(diffs),
            "diffs": diffs[:20],
            "verdict": "CONSISTENT" if not diffs else "DIVERGED",
        }


# ---------------------------------------------------------------------------
# Triage Documentation
# ---------------------------------------------------------------------------

def generate_triage_doc(run_id: str, db_path: str = DEFAULT_DB_PATH) -> str:
    """
    Generate triage documentation for a failed run.
    Identifies which phases failed, why, and suggests fixes.
    """
    viewer = JudgmentLedgerViewer(db_path)
    entries = viewer.get_run(run_id)

    if not entries:
        return f"No entries found for run {run_id}"

    # Group by phase
    phases: Dict[str, List[dict]] = {}
    for e in entries:
        phases.setdefault(e.get("phase", "unknown"), []).append(e)

    lines = [
        "# Marina E2E Triage Report",
        f"Run ID: {run_id}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    for phase, phase_entries in phases.items():
        scores = [e["score"] for e in phase_entries if e.get("score") is not None]
        avg = sum(scores) / len(scores) if scores else 0
        lines.append(f"## {phase} (avg score: {avg:.2f})")

        # Find low-scoring dimensions
        low = [e for e in phase_entries if (e.get("score") or 0) < 6.0]
        if low:
            lines.append("### Low-scoring dimensions:")
            for e in low:
                lines.append(f"- **{e.get('dimension_id')}**: {e.get('score', 0):.1f}/10")
                lines.append(f"  Reasoning: {(e.get('reasoning') or 'N/A')[:150]}")
                lines.append("")

        # Find abstentions
        abstained = [e for e in phase_entries if e.get("tool_calls_used", 0) == 0 and (e.get("score") or 0) == 0]
        if abstained:
            lines.append(f"### Abstentions: {len(abstained)} dimensions could not be scored")
            lines.append("")

    lines.append("## Suggested Actions")
    lines.append("1. Check DB for missing evidence (plan_evidence table)")
    lines.append("2. Verify BFT consensus fired (bft_votes table)")
    lines.append("3. Check physics violation ledger for unresolved hard violations")
    lines.append("4. Review ARVIS logs for tool execution failures")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

async def cli_main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="marina",
        description="Marina E2E v3 — CI Test Runner",
    )
    subparsers = parser.add_subparsers(dest="command")

    # marina test
    test_parser = subparsers.add_parser("test", help="Run E2E tests")
    test_parser.add_argument("--mode", choices=["smoke", "standard", "full"], default="smoke")
    test_parser.add_argument("--format", choices=["text", "json", "junit"], default="text")
    test_parser.add_argument("--output", help="Output file path")
    test_parser.add_argument("--db-path", default=DEFAULT_DB_PATH)

    # marina view
    view_parser = subparsers.add_parser("view", help="View judgment ledger")
    view_parser.add_argument("--run-id", help="Specific run ID")
    view_parser.add_argument("--phase", help="Filter by phase")
    view_parser.add_argument("--list", action="store_true", help="List recent runs")
    view_parser.add_argument("--db-path", default=DEFAULT_DB_PATH)

    # marina replay
    replay_parser = subparsers.add_parser("replay", help="Replay a previous run")
    replay_parser.add_argument("run_id", help="Run ID to replay")
    replay_parser.add_argument("--db-path", default=DEFAULT_DB_PATH)

    # marina triage
    triage_parser = subparsers.add_parser("triage", help="Generate triage doc for failed run")
    triage_parser.add_argument("run_id", help="Run ID to triage")
    triage_parser.add_argument("--db-path", default=DEFAULT_DB_PATH)

    args = parser.parse_args()

    if args.command == "test":
        runner = CIRunner(
            mode=args.mode,
            db_path=args.db_path,
            output_format=args.format,
            output_path=args.output,
        )
        exit_code = await runner.run()
        sys.exit(exit_code)

    elif args.command == "view":
        viewer = JudgmentLedgerViewer(args.db_path)
        if args.list:
            runs = viewer.list_runs()
            for r in runs:
                print(f"  {r['run_id']}: {r['n_judgments']} judgments, avg={r['avg_score']:.2f}")
        elif args.run_id:
            if args.phase:
                entries = viewer.get_phase(args.run_id, args.phase)
            else:
                entries = viewer.get_run(args.run_id)
            for e in entries:
                print(viewer.format_entry(e))
                print("-" * 40)

    elif args.command == "replay":
        engine = ReplayEngine(args.db_path)
        result = await engine.replay_run(args.run_id)
        print(json.dumps(result, indent=2))

    elif args.command == "triage":
        doc = generate_triage_doc(args.run_id, args.db_path)
        print(doc)

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(cli_main())
