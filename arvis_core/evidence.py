"""
Evidence Ledger
===============

Structured evidence objects for ARVIS swarm.

Every tool result and retrieved document chunk becomes an Evidence record.
The LLM reasons over evidence — it never authors evidence.
Final synthesis receives ONLY ledger entries as factual source.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class FreshnessStatus(Enum):
    LIVE = "live"           # < 5 min old
    RECENT = "recent"       # 5-15 min old
    STALE = "stale"         # > 15 min old
    UNKNOWN = "unknown"     # no timestamp available


@dataclass
class Evidence:
    """A single piece of grounded evidence from a tool result or document chunk."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source_tool: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    node_name: str = ""
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    plan_task_id: Optional[str] = None
    call_sig: Optional[str] = None
    summary: str = ""
    # Equipment binding — set by snapshot promoter so ledger entries are unambiguously tied to one device
    equipment_id: Optional[str] = None
    equipment_type: Optional[str] = None
    # ML lineage (WS-M1/M2)
    is_ml_fallback: bool = False
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    algorithm: Optional[str] = None
    confidence_bounds: Optional[Dict[str, float]] = None
    drift_score: Optional[float] = None
    training_window: Optional[str] = None

    @classmethod
    def from_tool_result(
        cls,
        tool_name: str,
        result: Dict[str, Any],
        node_name: str = "",
        task_id: Optional[str] = None,
    ) -> "Evidence":
        if result.get("error"):
            return cls(
                source_tool=tool_name,
                raw_payload=result,
                node_name=node_name,
                plan_task_id=task_id,
                freshness=FreshnessStatus.UNKNOWN,
                summary=f"Error from {tool_name}: {result.get('error')}",
            )

        is_ml_fallback = result.get("fallback") is True or result.get("ml_status") == "unavailable"
        if is_ml_fallback:
            return cls(
                source_tool=tool_name,
                raw_payload=result,
                node_name=node_name,
                plan_task_id=task_id,
                freshness=FreshnessStatus.UNKNOWN,
                summary=f"ML FALLBACK from {tool_name}: {result.get('reason', 'model unavailable')}",
                is_ml_fallback=True,
            )

        ml_meta = result.get("_ml_lineage", {})
        return cls(
            source_tool=tool_name,
            raw_payload=result,
            node_name=node_name,
            plan_task_id=task_id,
            freshness=FreshnessStatus.LIVE,
            summary=f"Result from {tool_name}",
            model_id=ml_meta.get("model_id"),
            model_version=ml_meta.get("model_version"),
            algorithm=ml_meta.get("algorithm"),
            confidence_bounds=ml_meta.get("confidence_bounds"),
            drift_score=ml_meta.get("drift_score"),
            training_window=ml_meta.get("training_window"),
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Evidence":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:12]),
            source_tool=d.get("source_tool", ""),
            raw_payload=d.get("raw_payload", {}),
            timestamp=datetime.fromisoformat(d["timestamp"]) if "timestamp" in d else datetime.now(timezone.utc),
            node_name=d.get("node_name", ""),
            freshness=FreshnessStatus(d.get("freshness", FreshnessStatus.UNKNOWN.value)),
            plan_task_id=d.get("plan_task_id"),
            call_sig=d.get("call_sig"),
            summary=d.get("summary", ""),
            is_ml_fallback=d.get("is_ml_fallback", False),
            equipment_id=d.get("equipment_id"),
            equipment_type=d.get("equipment_type"),
            model_id=d.get("model_id"),
            model_version=d.get("model_version"),
            algorithm=d.get("algorithm"),
            confidence_bounds=d.get("confidence_bounds"),
            drift_score=d.get("drift_score"),
            training_window=d.get("training_window"),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "source_tool": self.source_tool,
            "raw_payload": self.raw_payload,
            "timestamp": self.timestamp.isoformat(),
            "node_name": self.node_name,
            "freshness": self.freshness.value,
            "plan_task_id": self.plan_task_id,
            "call_sig": self.call_sig,
            "summary": self.summary,
            "is_ml_fallback": self.is_ml_fallback,
        }
        if self.equipment_id is not None:
            d["equipment_id"] = self.equipment_id
        if self.equipment_type is not None:
            d["equipment_type"] = self.equipment_type
        if self.model_id is not None:
            d["model_id"] = self.model_id
        if self.model_version is not None:
            d["model_version"] = self.model_version
        if self.algorithm is not None:
            d["algorithm"] = self.algorithm
        if self.confidence_bounds is not None:
            d["confidence_bounds"] = self.confidence_bounds
        if self.drift_score is not None:
            d["drift_score"] = self.drift_score
        if self.training_window is not None:
            d["training_window"] = self.training_window
        return d


class EvidenceLedger:
    """
    Per-investigation evidence store.

    All nodes write evidence here. Synthesis reads from here.
    Numbers in the final response must trace to an evidence.id.
    """

    def __init__(self) -> None:
        self._entries: List[Evidence] = []
        self._by_id: Dict[str, Evidence] = {}

    def add(self, evidence: Evidence) -> str:
        self._entries.append(evidence)
        self._by_id[evidence.id] = evidence
        return evidence.id

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._by_id.get(evidence_id)

    def get_all(self) -> List[Evidence]:
        return list(self._entries)

    def get_by_tool(self, tool_name: str) -> List[Evidence]:
        return [e for e in self._entries if e.source_tool == tool_name]

    def get_by_call_sig(self, call_sig: str) -> Optional[Evidence]:
        """Find evidence by exact tool call signature (tool_name:args_hash)."""
        for e in self._entries:
            if e.call_sig == call_sig:
                return e
        return None

    def get_by_task(self, task_id: str) -> List[Evidence]:
        return [e for e in self._entries if e.plan_task_id == task_id]

    def get_by_node(self, node_name: str) -> List[Evidence]:
        return [e for e in self._entries if e.node_name == node_name]

    def has_evidence_for(self, tool_name: str) -> bool:
        return any(e.source_tool == tool_name for e in self._entries)

    def numeric_values(self) -> Dict[str, float]:
        """Extract all numeric values across all evidence for grounding checks."""
        nums: Dict[str, float] = {}
        for e in self._entries:
            self._extract_nums(e.raw_payload, f"{e.id}:", nums)
        return nums

    def _extract_nums(self, obj: Any, prefix: str, out: Dict[str, float], depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            out[f"{prefix}{obj}"] = float(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._extract_nums(v, f"{prefix}{k}.", out, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for i, item in enumerate(obj):
                self._extract_nums(item, f"{prefix}[{i}].", out, depth + 1)

    def to_synthesis_context(self) -> str:
        """Format ledger for injection into synthesis prompt."""
        if not self._entries:
            return "No evidence collected."
        import json
        lines = []
        for e in self._entries:
            if e.is_ml_fallback:
                tag = " [ML_FALLBACK]"
            elif e.model_id:
                drift_str = f", drift={e.drift_score:.2f}" if e.drift_score is not None else ""
                ver_str = f"/{e.model_version}" if e.model_version else ""
                tag = f" [ML: {e.model_id}{ver_str}{drift_str}]"
            else:
                tag = ""
            eq_tag = f" [EQ:{e.equipment_id}]" if e.equipment_id else ""
            lines.append(f"[{e.id}]{eq_tag} {e.source_tool} ({e.node_name}){tag}: {e.summary}")
            if e.raw_payload and not e.raw_payload.get("error"):
                payload = {k: v for k, v in e.raw_payload.items() if k != "_ml_lineage"}
                lines.append(f"  DATA: {json.dumps(payload, default=str)[:400]}")
        return "\n".join(lines)

    def to_list(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entries]

    @classmethod
    def from_list(cls, entries: List[Dict[str, Any]]) -> "EvidenceLedger":
        ledger = cls()
        for d in entries:
            ledger.add(Evidence.from_dict(d))
        return ledger

    def __len__(self) -> int:
        return len(self._entries)
