"""
Skill Grounding Gate
====================

Stage 3 of the manual→skill compiler — the anti-hallucination line.

Every structured item in a CompiledSkill must be attributable to real source
pages before the skill is published. The gate:
  * rejects items whose source_pages are empty or out of the manual's page range;
  * (strict mode) rejects items whose cited pages contain no lexical support for
    the item's key terms — catching a model that cites a page it did not read;
  * computes a per-skill grounding confidence = fraction of items that pass;
  * assigns status: `active` if confidence >= threshold, else `flagged` for human
    review. A flagged skill is still written but never silently trusted.

This mirrors the philosophy of grounding_guard.py (numeric claims must trace to a
tool result); here, structural claims must trace to a source page.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agent_commercial.skills.skill_analyzer import CompiledSkill

logger = logging.getLogger("arvis.skills.grounding")

# Skill is published as `active` at/above this fraction of grounded items.
GROUNDING_THRESHOLD = 0.75
# In strict mode, an item's cited pages must share at least this fraction of the
# item's salient tokens, else it's treated as an unsupported citation.
LEXICAL_SUPPORT_MIN = 0.3
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "be", "on",
    "for", "with", "at", "by", "if", "then", "this", "that", "should", "must",
    "not", "no", "high", "low", "when", "which", "it", "its",
}


@dataclass
class GroundingReport:
    total_items: int = 0
    grounded_items: int = 0
    dropped_out_of_range: int = 0
    dropped_unsupported: int = 0
    confidence: float = 0.0
    status: str = "flagged"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_items": self.total_items,
            "grounded_items": self.grounded_items,
            "dropped_out_of_range": self.dropped_out_of_range,
            "dropped_unsupported": self.dropped_unsupported,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "notes": self.notes[:20],
        }


class SkillGroundingGate:
    def __init__(self, strict: bool = True, threshold: float = GROUNDING_THRESHOLD) -> None:
        self.strict = strict
        self.threshold = threshold

    def check(
        self,
        skill: CompiledSkill,
        page_count: int,
        page_text_by_no: dict[int, str] | None = None,
    ) -> GroundingReport:
        """Validate and prune `skill` in place. Returns a GroundingReport.

        page_text_by_no enables strict lexical-support checking; without it, only
        the range check runs.
        """
        report = GroundingReport()

        def valid_pages(pages: list[int]) -> bool:
            return bool(pages) and all(1 <= p <= page_count for p in pages)

        def supported(text_terms: set[str], pages: list[int]) -> bool:
            if not self.strict or not page_text_by_no:
                return True
            if not text_terms:
                return True
            corpus = " ".join(page_text_by_no.get(p, "") for p in pages).lower()
            if not corpus.strip():
                return False
            hits = sum(1 for t in text_terms if t in corpus)
            return (hits / len(text_terms)) >= LEXICAL_SUPPORT_MIN

        def salient(*fields: str) -> set[str]:
            toks = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", " ".join(fields).lower())
            return {t for t in toks if t not in _STOPWORDS}

        def filter_list(items, term_fields):
            kept = []
            for it in items:
                report.total_items += 1
                pages = it.source_pages
                if not valid_pages(pages):
                    report.dropped_out_of_range += 1
                    report.notes.append(f"out-of-range pages {pages}: {term_fields(it)[:60]}")
                    continue
                terms = salient(*[getattr(it, f) for f in _TERM_FIELDS.get(type(it).__name__, [])])
                if not supported(terms, pages):
                    report.dropped_unsupported += 1
                    report.notes.append(f"unsupported cite p{pages}: {term_fields(it)[:60]}")
                    continue
                report.grounded_items += 1
                kept.append(it)
            return kept

        def label(it):
            for f in ("name", "warning", "condition"):
                if hasattr(it, f):
                    return getattr(it, f)
            return ""

        skill.frameworks = filter_list(skill.frameworks, label)
        skill.critical_parameters = filter_list(skill.critical_parameters, label)
        skill.decision_rules = filter_list(skill.decision_rules, label)
        skill.anti_patterns = filter_list(skill.anti_patterns, label)
        skill.fault_patterns = filter_list(skill.fault_patterns, label)

        if report.total_items:
            report.confidence = report.grounded_items / report.total_items
        else:
            report.confidence = 0.0
            report.notes.append("no structured items extracted")
        report.status = "active" if (report.total_items and report.confidence >= self.threshold) else "flagged"

        logger.info("Grounding %s: %s", skill.equipment_name, report.to_dict())
        return report


# salient-term fields per item type, for lexical-support checking
_TERM_FIELDS = {
    "Framework": ["name", "description"],
    "CriticalParameter": ["name", "normal_range"],
    "DecisionRule": ["condition", "action"],
    "AntiPattern": ["warning"],
    "FaultPattern": ["name", "symptom_signature", "root_cause"],
}
