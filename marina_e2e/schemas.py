"""Data structures for the Marina agentic judge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """Structured result from a verification tool."""
    ok: bool
    data: Any = None
    error: str = ""
    tool_name: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if not self.ok:
            return f"ERROR: {self.error}"
        if isinstance(self.data, list):
            return f"{len(self.data)} records"
        if isinstance(self.data, dict):
            keys = list(self.data.keys())[:5]
            return f"dict with keys: {keys}"
        return str(self.data)[:200]


@dataclass
class EvidenceLink:
    """One link in a judgment evidence chain."""
    tool: str
    params: Dict[str, Any]
    result_summary: str
    finding: str = ""


@dataclass
class JudgmentEntry:
    """Score for a single dimension with forensic evidence chain."""
    dimension_id: str
    score: float
    reasoning: str
    evidence_chain: List[EvidenceLink] = field(default_factory=list)
    tool_calls_used: int = 0
    abstained: bool = False
    abstain_reason: str = ""
    wall_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "score": self.score,
            "reasoning": self.reasoning,
            "evidence_chain": [
                {"tool": e.tool, "params": e.params,
                 "result_summary": e.result_summary, "finding": e.finding}
                for e in self.evidence_chain
            ],
            "tool_calls_used": self.tool_calls_used,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "wall_time_ms": self.wall_time_ms,
        }


@dataclass
class PhaseWindow:
    """Time bounds for a Marina phase execution."""
    phase: str
    scenario: str
    t_start: str
    t_end: str
    plan_ids: List[str] = field(default_factory=list)
    operator_id: str = ""
    building_id: str = ""


@dataclass
class ConsistencyFinding:
    """A cross-phase consistency issue found by the checker."""
    check_type: str
    phase_a: str
    phase_b: str
    equipment_id: str = ""
    description: str = ""
    severity: str = "warning"
