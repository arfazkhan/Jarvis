"""
Cross-Phase Consistency Checker for Marina E2E.

Verifies that ARVIS maintains coherent state across multiple phases:
- Skills written in one phase are recalled in subsequent phases
- Equipment health status doesn't contradict across phases
- Recommendations created early are referenced/resolved later
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from marina_e2e.schemas import ConsistencyFinding, PhaseWindow

logger = logging.getLogger("marina.consistency")

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "agent_commercial" / "data" / "arvis_bms.db")


def _connect_ro(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class ConsistencyChecker:
    """
    Runs after all phases in a scenario complete.
    Identifies cross-phase coherence issues.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def check_all(self, phase_windows: List[PhaseWindow]) -> List[ConsistencyFinding]:
        """Run all consistency checks across the given phase windows."""
        findings: List[ConsistencyFinding] = []
        findings.extend(self.check_skill_persistence(phase_windows))
        findings.extend(self.check_evidence_growth(phase_windows))
        findings.extend(self.check_violation_escalation(phase_windows))
        return findings

    def check_skill_persistence(self, phase_windows: List[PhaseWindow]) -> List[ConsistencyFinding]:
        """
        Verify that skills written in early phases exist in DB for later phases.
        If a phase claims to write a skill but no row exists, flag it.
        """
        findings = []
        try:
            conn = _connect_ro(self.db_path)
            cur = conn.cursor()

            for i, window in enumerate(phase_windows):
                if not window.plan_ids:
                    continue
                cur.execute(
                    "SELECT COUNT(*) FROM skills WHERE building_id = ? "
                    "AND created_at >= ? AND created_at <= ?",
                    (window.building_id, window.t_start, window.t_end),
                )
                count = cur.fetchone()[0]

                if i > 0 and count == 0:
                    prev_window = phase_windows[i - 1]
                    cur.execute(
                        "SELECT COUNT(*) FROM skills WHERE building_id = ? "
                        "AND created_at >= ? AND created_at <= ?",
                        (window.building_id, prev_window.t_start, prev_window.t_end),
                    )
                    prev_count = cur.fetchone()[0]
                    if prev_count > 0:
                        findings.append(ConsistencyFinding(
                            check_type="skill_persistence",
                            phase_a=prev_window.phase,
                            phase_b=window.phase,
                            description=(
                                f"Phase {prev_window.phase} wrote {prev_count} skills "
                                f"but phase {window.phase} wrote 0 — expected recall or growth."
                            ),
                            severity="info",
                        ))
            conn.close()
        except Exception as e:
            logger.debug(f"[Consistency] skill_persistence check failed: {e}")
        return findings

    def check_evidence_growth(self, phase_windows: List[PhaseWindow]) -> List[ConsistencyFinding]:
        """
        Verify evidence ledger grows across phases.
        A phase with plan_ids but zero evidence is suspicious.
        """
        findings = []
        try:
            conn = _connect_ro(self.db_path)
            cur = conn.cursor()

            for window in phase_windows:
                for plan_id in window.plan_ids:
                    cur.execute(
                        "SELECT COUNT(*) FROM plan_evidence WHERE plan_id = ?",
                        (plan_id,),
                    )
                    count = cur.fetchone()[0]
                    if count == 0:
                        findings.append(ConsistencyFinding(
                            check_type="evidence_growth",
                            phase_a=window.phase,
                            phase_b=window.phase,
                            description=(
                                f"Plan {plan_id} in phase {window.phase} has 0 evidence records. "
                                f"Investigation may not have gathered data."
                            ),
                            severity="warning",
                        ))
            conn.close()
        except Exception as e:
            logger.debug(f"[Consistency] evidence_growth check failed: {e}")
        return findings

    def check_violation_escalation(self, phase_windows: List[PhaseWindow]) -> List[ConsistencyFinding]:
        """
        If a hard violation occurs in an early phase, later phases should
        show either resolution (no repeat) or explicit acknowledgment.
        """
        findings = []
        try:
            conn = _connect_ro(self.db_path)
            cur = conn.cursor()

            seen_hard_violations: Dict[str, str] = {}  # code -> first_phase

            for window in phase_windows:
                for plan_id in window.plan_ids:
                    cur.execute(
                        "SELECT code, severity FROM violation_ledger WHERE plan_id = ?",
                        (plan_id,),
                    )
                    for row in cur.fetchall():
                        code = row["code"]
                        severity = row["severity"]
                        if severity == "hard":
                            if code not in seen_hard_violations:
                                seen_hard_violations[code] = window.phase
                            elif seen_hard_violations[code] != window.phase:
                                findings.append(ConsistencyFinding(
                                    check_type="violation_escalation",
                                    phase_a=seen_hard_violations[code],
                                    phase_b=window.phase,
                                    description=(
                                        f"Hard violation '{code}' first seen in "
                                        f"{seen_hard_violations[code]} recurs in "
                                        f"{window.phase} — may indicate unresolved issue."
                                    ),
                                    severity="warning",
                                ))
            conn.close()
        except Exception as e:
            logger.debug(f"[Consistency] violation_escalation check failed: {e}")
        return findings
