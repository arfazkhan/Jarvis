"""
ARVIS Memory Types
==================

Shared dataclasses and enums for the 7-tier unified memory architecture.
All memory operations use these types as currency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryTier(Enum):
    T1_WORKING = "t1_working"           # ConversationBuffer + active InvestigationPlan
    T2_EPISODIC = "t2_episodic"         # Per-investigation archive (SQLite)
    T3_PROCEDURAL = "t3_procedural"     # distilled_rules + OperatorPatternStore
    T4_SEMANTIC = "t4_semantic"         # TechnicalKnowledgeBase + TreeKnowledgeBase
    T5_INSTITUTIONAL = "t5_institutional"  # BuildingSkillbook + WorldModel
    T6_IDENTITY = "t6_identity"         # PreferenceStore + operator persona
    T7_RESOLUTION = "t7_resolution"     # DeviceAliasResolver


@dataclass
class MemoryHit:
    """Single result from any memory tier — uniform currency for all reads."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    tier: MemoryTier = MemoryTier.T3_PROCEDURAL
    content: str = ""
    source: str = ""                  # e.g. "skillbook", "distilled_rules", "investigation:abc123"
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_link: Optional[str] = None   # evidence.id if this hit was already evidenced
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_context_line(self) -> str:
        tier_label = self.tier.value.upper()
        conf_str = f" (conf={self.confidence:.2f})" if self.confidence < 1.0 else ""
        return f"[{tier_label}:{self.source}]{conf_str} {self.content}"


@dataclass
class MemoryRecord:
    """Write payload for orchestrator.write() — passes through conflict resolver."""
    tier: MemoryTier
    content: str
    source: str = ""
    confidence: float = 0.7
    ttl_days: Optional[int] = None        # None = no expiry
    conflict_check: bool = True           # False = force write (bypass resolver)
    building_id: Optional[str] = None
    operator_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallBundle:
    """
    Auto-recall result injected into every investigation before nodes run.
    Aggregates relevant context from T2+T3+T5+T6 without any LLM tool call.
    """
    similar_investigations: List[MemoryHit] = field(default_factory=list)
    applicable_skills: List[MemoryHit] = field(default_factory=list)
    matching_patterns: List[MemoryHit] = field(default_factory=list)
    operator_prefs: List[MemoryHit] = field(default_factory=list)
    alias_map: Dict[str, str] = field(default_factory=dict)  # alias → canonical_id

    @property
    def is_empty(self) -> bool:
        return (
            not self.similar_investigations
            and not self.applicable_skills
            and not self.matching_patterns
            and not self.operator_prefs
        )

    def to_context_block(self) -> str:
        """Format for injection into node system prompt."""
        if self.is_empty:
            return ""
        lines = ["=== RECALL CONTEXT (auto-retrieved, no tool call needed) ==="]
        if self.similar_investigations:
            lines.append("SIMILAR PAST INVESTIGATIONS:")
            for h in self.similar_investigations[:3]:
                lines.append(f"  • {h.to_context_line()}")
        if self.applicable_skills:
            lines.append("RELEVANT BUILDING SKILLS:")
            for h in self.applicable_skills[:3]:
                lines.append(f"  • {h.to_context_line()}")
        if self.matching_patterns:
            lines.append("MATCHING OPERATOR PATTERNS:")
            for h in self.matching_patterns[:3]:
                lines.append(f"  • {h.to_context_line()}")
        if self.operator_prefs:
            lines.append("OPERATOR PREFERENCES:")
            for h in self.operator_prefs[:2]:
                lines.append(f"  • {h.to_context_line()}")
        if self.alias_map:
            lines.append(f"DEVICE ALIASES: {self.alias_map}")
        lines.append("=== END RECALL CONTEXT ===")
        return "\n".join(lines)


@dataclass
class ConversationContext:
    """T1 working memory — buffered turns + rolling summary for chat()."""
    operator_id: str = ""
    building_id: str = ""
    turns: List[Dict[str, str]] = field(default_factory=list)   # [{role, content}]
    rolling_summary: str = ""
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_history(self) -> List[Dict[str, str]]:
        """Return turns preceded by summary turn if summary exists."""
        if self.rolling_summary:
            return [{"role": "system", "content": f"[Prior context summary] {self.rolling_summary}"}] + self.turns
        return list(self.turns)


@dataclass
class StoreHealth:
    """Health ping result from an adapter."""
    tier: MemoryTier
    healthy: bool
    latency_ms: float = 0.0
    record_count: int = 0
    error: Optional[str] = None
