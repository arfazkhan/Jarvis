"""
Investigation Plan
==================

Externalized plan-track-recall-verify architecture for ARVIS.

Every ARVIS investigation is driven by an InvestigationPlan object.
The model reads/writes the plan — it does not hold it in context.
Every step writes a Span to the audit trail. Every conclusion traces
to a plan step → tool call → evidence id → verifier verdict.

This replaces the prompt-text "mental Todo List" with code state.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from arvis_core.evidence import EvidenceLedger


class TaskStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETE = "complete"
    ABANDONED = "abandoned"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class Budget:
    """Per-investigation resource budget shared across all swarm nodes."""
    max_tool_calls: int = 24
    max_tokens: int = 500000
    max_wall_seconds: float = 120.0
    max_cost_usd: float = 1.00
    used_tool_calls: int = 0
    used_tokens: int = 0
    used_wall_seconds: float = 0.0
    used_cost_usd: float = 0.0

    @property
    def tool_calls_remaining(self) -> int:
        return max(0, self.max_tool_calls - self.used_tool_calls)

    @property
    def exhausted(self) -> bool:
        return (
            self.used_tool_calls >= self.max_tool_calls
            or self.used_tokens >= self.max_tokens
            or self.used_wall_seconds >= self.max_wall_seconds
            or self.used_cost_usd >= self.max_cost_usd
        )

    def record_tool_call(self, tokens_used: int = 0, cost_usd: float = 0.0) -> None:
        self.used_tool_calls += 1
        self.used_tokens += tokens_used
        self.used_cost_usd += cost_usd

    def record_llm_call(self, input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0) -> None:
        """Record LLM inference cost (separate from tool call counter)."""
        self.used_tokens += input_tokens + output_tokens
        self.used_cost_usd += cost_usd

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_calls": f"{self.used_tool_calls}/{self.max_tool_calls}",
            "tokens": f"{self.used_tokens}/{self.max_tokens}",
            "wall_seconds": f"{self.used_wall_seconds:.1f}/{self.max_wall_seconds:.1f}",
            "cost_usd": f"${self.used_cost_usd:.4f}/${self.max_cost_usd:.2f}",
            "exhausted": self.exhausted,
        }

    def to_raw_dict(self) -> Dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_wall_seconds": self.max_wall_seconds,
            "max_cost_usd": self.max_cost_usd,
            "used_tool_calls": self.used_tool_calls,
            "used_tokens": self.used_tokens,
            "used_wall_seconds": self.used_wall_seconds,
            "used_cost_usd": self.used_cost_usd,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Budget":
        return cls(
            max_tool_calls=d.get("max_tool_calls", 24),
            max_tokens=d.get("max_tokens", 500000),
            max_wall_seconds=d.get("max_wall_seconds", 120.0),
            max_cost_usd=d.get("max_cost_usd", 1.00),
            used_tool_calls=d.get("used_tool_calls", 0),
            used_tokens=d.get("used_tokens", 0),
            used_wall_seconds=d.get("used_wall_seconds", 0.0),
            used_cost_usd=d.get("used_cost_usd", 0.0),
        )


@dataclass
class Span:
    """Audit trail entry for one step of an investigation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_id: str = ""
    node_name: str = ""
    action: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    evidence_id: Optional[str] = None
    verdict: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Span":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            task_id=d.get("task_id", ""),
            node_name=d.get("node_name", ""),
            action=d.get("action", ""),
            tool_name=d.get("tool_name"),
            tool_args=d.get("tool_args"),
            evidence_id=d.get("evidence_id"),
            verdict=d.get("verdict"),
            timestamp=datetime.fromisoformat(d["timestamp"]) if "timestamp" in d else datetime.now(timezone.utc),
            duration_ms=d.get("duration_ms", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "task_id": self.task_id,
            "node_name": self.node_name,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.tool_args:
            d["tool_args"] = self.tool_args
        if self.evidence_id:
            d["evidence_id"] = self.evidence_id
        if self.verdict:
            d["verdict"] = self.verdict
        return d


@dataclass
class Task:
    """A single step in an investigation plan."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str = ""
    tool_hint: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    expected_outcome: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    attempts: int = 0
    assigned_node: Optional[str] = None

    def mark_complete(self, evidence_id: Optional[str] = None) -> None:
        self.status = TaskStatus.COMPLETE
        if evidence_id:
            self.evidence_ids.append(evidence_id)

    def mark_failed(self) -> None:
        self.status = TaskStatus.FAILED
        self.attempts += 1

    def mark_active(self) -> None:
        self.status = TaskStatus.ACTIVE
        self.attempts += 1

    @property
    def has_evidence(self) -> bool:
        return len(self.evidence_ids) > 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Task":
        t = cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            goal=d.get("goal", ""),
            tool_hint=d.get("tool_hint"),
            status=TaskStatus(d.get("status", TaskStatus.PENDING.value)),
            expected_outcome=d.get("expected_outcome", ""),
            evidence_ids=d.get("evidence_ids", []),
            attempts=d.get("attempts", 0),
            assigned_node=d.get("assigned_node"),
        )
        return t

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "tool_hint": self.tool_hint,
            "status": self.status.value,
            "expected_outcome": self.expected_outcome,
            "evidence_ids": self.evidence_ids,
            "attempts": self.attempts,
            "assigned_node": self.assigned_node,
        }


@dataclass
class InvestigationPlan:
    """
    Externalized plan for an ARVIS investigation.

    The model reads this at each step. The model writes to it after each step.
    The operator sees tasks tick off live. Replay = read audit_trail.
    Resume = load from disk, continue from first pending task.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    query: str = ""
    tasks: List[Task] = field(default_factory=list)
    evidence: EvidenceLedger = field(default_factory=EvidenceLedger)
    budget: Budget = field(default_factory=Budget)
    status: PlanStatus = PlanStatus.ACTIVE
    audit_trail: List[Span] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _shared_call_sigs: set = field(default_factory=set, repr=False)
    _tool_cache: dict = field(default_factory=dict, repr=False)

    # ── Cross-node spin dedup ───────────────────────────────────────────

    def is_duplicate_call(self, call_sig: str) -> bool:
        """Check if this tool call signature was already executed by any node."""
        return call_sig in self._shared_call_sigs

    def register_call(self, call_sig: str) -> None:
        """Register a tool call signature as executed."""
        self._shared_call_sigs.add(call_sig)

    # ── Cross-node tool result cache (T1.3) ─────────────────────────────

    def cache_tool_result(self, call_sig: str, result: dict) -> None:
        """Cache a successful tool result so other nodes can reuse it."""
        self._tool_cache[call_sig] = result

    def get_cached_tool_result(self, call_sig: str) -> Optional[dict]:
        """Return cached result for call_sig, or None if not cached."""
        return self._tool_cache.get(call_sig)

    # ── Task management ──────────────────────────────────────────────────

    def add_task(self, goal: str, tool_hint: Optional[str] = None, expected_outcome: str = "") -> Task:
        task = Task(goal=goal, tool_hint=tool_hint, expected_outcome=expected_outcome)
        self.tasks.append(task)
        return task

    def next_pending_task(self) -> Optional[Task]:
        for t in self.tasks:
            if t.status == TaskStatus.PENDING:
                return t
        return None

    def current_active_task(self) -> Optional[Task]:
        for t in self.tasks:
            if t.status == TaskStatus.ACTIVE:
                return t
        return None

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED))
        return done / len(self.tasks)

    @property
    def all_done(self) -> bool:
        return all(t.status in (TaskStatus.COMPLETE, TaskStatus.SKIPPED, TaskStatus.FAILED) for t in self.tasks)

    @property
    def coverage(self) -> float:
        """Fraction of tasks with at least one evidence id — used for data_coverage score."""
        if not self.tasks:
            return 0.0
        covered = sum(1 for t in self.tasks if t.has_evidence)
        return covered / len(self.tasks)

    # ── Audit trail ──────────────────────────────────────────────────────

    def record_span(self, **kwargs) -> Span:
        span = Span(**kwargs)
        self.audit_trail.append(span)
        return span

    # ── Budget check ─────────────────────────────────────────────────────

    def check_budget(self) -> bool:
        """Returns True if budget still available. If exhausted, marks plan status."""
        if self.budget.exhausted:
            self.status = PlanStatus.BUDGET_EXHAUSTED
            return False
        return True

    # ── Serialization ────────────────────────────────────────────────────

    def to_prompt_context(self) -> str:
        """Inject into node prompt so model sees plan state."""
        lines = [f"INVESTIGATION PLAN (id={self.id}, progress={self.progress:.0%}):"]
        lines.append(f"  Query: {self.query}")
        lines.append(f"  Budget: {self.budget.to_dict()}")
        lines.append("  Tasks:")
        for t in self.tasks:
            marker = {"pending": "[ ]", "active": "[>]", "complete": "[x]", "failed": "[!]", "skipped": "[-]"}
            lines.append(f"    {marker.get(t.status.value, '[ ]')} {t.id}: {t.goal}")
            if t.evidence_ids:
                lines.append(f"        evidence: {', '.join(t.evidence_ids)}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Display-oriented serialization (budget as human strings, no evidence entries)."""
        return {
            "id": self.id,
            "query": self.query,
            "tasks": [t.to_dict() for t in self.tasks],
            "budget": self.budget.to_dict(),
            "status": self.status.value,
            "progress": self.progress,
            "coverage": self.coverage,
            "audit_trail": [s.to_dict() for s in self.audit_trail],
            "evidence_count": len(self.evidence),
            "created_at": self.created_at.isoformat(),
        }

    def to_persist_dict(self) -> Dict[str, Any]:
        """Full roundtrip-safe serialization — includes evidence entries and raw budget values."""
        return {
            "_schema_version": 1,
            "id": self.id,
            "query": self.query,
            "tasks": [t.to_dict() for t in self.tasks],
            "budget": self.budget.to_raw_dict(),
            "status": self.status.value,
            "audit_trail": [s.to_dict() for s in self.audit_trail],
            "evidence": self.evidence.to_list(),
            "shared_call_sigs": list(self._shared_call_sigs),
            "tool_cache": self._tool_cache,
            "created_at": self.created_at.isoformat(),
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_persist_dict(), default=str, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, raw: str) -> "InvestigationPlan":
        from arvis_core.evidence import EvidenceLedger
        data = json.loads(raw)
        plan = cls.__new__(cls)
        plan.id = data.get("id", str(uuid.uuid4())[:12])
        plan.query = data.get("query", "")
        plan.status = PlanStatus(data.get("status", PlanStatus.ACTIVE.value))
        plan.created_at = datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc)
        plan.tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        plan.audit_trail = [Span.from_dict(s) for s in data.get("audit_trail", [])]
        plan.budget = Budget.from_dict(data.get("budget", {}))
        plan.evidence = EvidenceLedger.from_list(data.get("evidence", []))
        plan._shared_call_sigs = set(data.get("shared_call_sigs", []))
        plan._tool_cache = data.get("tool_cache", {})
        return plan

    @classmethod
    def load(cls, path: Path) -> "InvestigationPlan":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2)
