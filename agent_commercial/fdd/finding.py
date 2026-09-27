"""
FaultFinding — the one result type every FDD rule produces.

Four outcomes (after NIST ZandrEA), so "no fault" is never confused with
"couldn't tell":

  PASS     rule evaluated on enough running data; no confirmed fault
  FAIL     confirmed fault (persisted past the rule's confirmation delay)
  SKIP     rule did not apply or could not run (missing points, equipment
           off, no run proof, unconfigured site parameter, design says N/A)
  INVALID  rule could run but a required sensor failed validation, so the
           result cannot be trusted either way
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    INVALID = "invalid"


@dataclass
class FaultFinding:
    rule_id: str
    title: str
    family: str
    equipment_id: str
    equipment_kind: str
    outcome: Outcome
    reason: str = ""
    summary: str = ""
    fault_hours: Optional[float] = None
    fault_pct: Optional[float] = None
    active_hours: Optional[float] = None
    sample_count: int = 0
    fault_sample_count: int = 0
    invalid_sample_count: int = 0
    first_fault: Optional[str] = None
    last_fault: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    missing_roles: List[str] = field(default_factory=list)
    invalid_roles: List[str] = field(default_factory=list)
    points_used: Dict[str, str] = field(default_factory=dict)      # role → point_id
    role_sources: Dict[str, str] = field(default_factory=dict)     # role → explicit|suggested|context
    params: Dict[str, Any] = field(default_factory=dict)
    params_fingerprint: str = ""
    gate_source: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    root_cause_candidates: List[str] = field(default_factory=list)
    origin: str = ""
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def source_tool(self) -> str:
        """Evidence-ledger source id: each rule is its own independent source."""
        return f"fdd:{self.rule_id}"

    @property
    def is_fault(self) -> bool:
        return self.outcome is Outcome.FAIL

    def headline(self) -> str:
        if self.outcome is Outcome.FAIL:
            return (f"{self.equipment_id}: {self.title} — confirmed {self.fault_hours:.1f} h "
                    f"({self.fault_pct:.0f}% of running time) [{self.rule_id}]")
        if self.outcome is Outcome.PASS:
            return f"{self.equipment_id}: {self.title} — no fault over {self.active_hours or 0:.1f} h [{self.rule_id}]"
        return f"{self.equipment_id}: {self.title} — {self.outcome.value}: {self.reason} [{self.rule_id}]"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id, "title": self.title, "family": self.family,
            "equipment_id": self.equipment_id, "equipment_kind": self.equipment_kind,
            "outcome": self.outcome.value, "reason": self.reason, "summary": self.summary,
            "headline": self.headline(),
            "fault_hours": self.fault_hours, "fault_pct": self.fault_pct,
            "active_hours": self.active_hours, "sample_count": self.sample_count,
            "fault_sample_count": self.fault_sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "first_fault": self.first_fault, "last_fault": self.last_fault,
            "window_start": self.window_start, "window_end": self.window_end,
            "missing_roles": list(self.missing_roles), "invalid_roles": list(self.invalid_roles),
            "points_used": dict(self.points_used), "role_sources": dict(self.role_sources),
            "params": dict(self.params), "params_fingerprint": self.params_fingerprint,
            "gate_source": self.gate_source, "metrics": dict(self.metrics),
            "root_cause_candidates": list(self.root_cause_candidates),
            "origin": self.origin, "source_tool": self.source_tool,
            "evaluated_at": self.evaluated_at,
        }
