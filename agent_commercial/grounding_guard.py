"""
Grounding Guard
===============

Structural anti-hallucination layer for ARVIS responses.

Every ARVIS response passes through here before reaching the operator.
The guard scans for cited numbers and checks each against tool-result
provenance tracked during the current conversation turn.

This is NOT a prompt rule — it runs in code, every time, regardless of
what the LLM was instructed. Prompt rules drift; this doesn't.

Architecture:
  GroundingGuard.register_tool_result(tool, result)  ← called by tool handler
  GroundingGuard.audit(response_text)                ← called before returning ChatResponse
  → returns AuditResult(clean_text, warnings, stripped_claims)

Design principles:
  - Never silently pass a fabricated number — always flag it
  - Never block a valid response — add a warning footer, don't suppress
  - Be conservative: only flag numbers that look like cited evidence
    (percentages, QAR amounts, probabilities, scores, time estimates)
    not conversational numbers ("2 AHUs", "Floor 12")
  - All warnings are logged; critical ones append a visible disclaimer
"""

from __future__ import annotations

import contextvars
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("arvis.grounding_guard")

# Per-request isolation: concurrent requests get independent guard state
_active_guard: contextvars.ContextVar["GroundingGuard"] = contextvars.ContextVar("_active_guard")


def get_active_guard() -> Optional["GroundingGuard"]:
    """Get the GroundingGuard for the current async request context."""
    return _active_guard.get(None)


def set_active_guard(guard: "GroundingGuard") -> contextvars.Token:
    """Set the GroundingGuard for the current async request context."""
    return _active_guard.set(guard)


# ── Patterns that identify "cited evidence" numbers in ARVIS text ─────────────
# These are numbers ARVIS presents as facts derived from analysis.
# We check whether they have tool-result provenance.

_EVIDENCE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Failure / probability claims
    ("failure_probability", re.compile(
        r"\b(\d{1,3})\s*%\s*(?:probability|chance|likelihood|risk)\s*(?:of\s*failure|of\s*breakdown|of\s*tripping)?",
        re.IGNORECASE,
    )),
    ("failure_in_days", re.compile(
        r"(?:failure|fails?|breakdown)\s*(?:probability|probability\s*within|within|in)\s*(\d+)\s*days?\s*[:\-–]\s*(\d{1,3})\s*%",
        re.IGNORECASE,
    )),
    # Health / efficiency scores
    ("health_score", re.compile(
        r"(?:health\s*score|efficiency\s*score|degradation\s*score)\s*[:\-–of]*\s*(\d{2,3})\s*(?:/\s*100|%)?",
        re.IGNORECASE,
    )),
    # QAR savings / cost claims
    ("qar_savings", re.compile(
        r"QAR\s*([\d,]+(?:\.\d+)?)\s*(?:/month|per\s*month|savings|saving|annual|/year)?",
        re.IGNORECASE,
    )),
    # Percentile rankings
    ("percentile", re.compile(
        r"(\d{1,3})(?:st|nd|rd|th)?\s*percentile",
        re.IGNORECASE,
    )),
    # Energy impact kwh
    ("energy_kwh", re.compile(
        r"([\d,]+(?:\.\d+)?)\s*kWh\s*(?:savings?|reduction|waste|per\s*month|/month|annual)",
        re.IGNORECASE,
    )),
    # Remaining useful life / days to failure
    ("rul_days", re.compile(
        r"(\d+)\s*days?\s*(?:until|before|to)\s*(?:predicted\s*)?(?:failure|breakdown|replacement|maintenance)",
        re.IGNORECASE,
    )),
    # COP values cited as analysis
    ("cop_value", re.compile(
        r"COP\s*(?:of|:|\s)\s*([\d.]+)\s*(?:kW/kW|kW\/kW)?",
        re.IGNORECASE,
    )),
]

# Numbers that are fine without provenance (conversational, counts, IDs)
_SAFE_CONTEXTS = re.compile(
    r"(?:floor|level|zone|ahu|ch|ct|vav|alarm|phase|step|item|point|day|hour|minute|week|month|year|"
    r"°[cCfF]|pa\b|mm/s|m²|kw\b(?!\s*h)|\bv\b|\ba\b|door|port|version|revision)\s*[-:]?\s*\d",
    re.IGNORECASE,
)


@dataclass
class GroundedValue:
    """A number that appeared in a tool result — valid to cite."""
    value_str: str          # string as it appeared
    tool_name: str
    source_key: str         # key path in tool result dict
    numeric: float


@dataclass
class UngroundedClaim:
    """A number ARVIS cited that has no tool-result provenance."""
    pattern_type: str
    cited_text: str         # the substring that triggered detection
    numeric: Optional[float]


@dataclass
class AuditResult:
    """Result of grounding audit on one ARVIS response."""
    original_text: str
    clean_text: str                         # text with disclaimer appended if needed
    ungrounded_claims: List[UngroundedClaim]
    grounded_values_used: List[str]         # tool names that provided cited numbers
    passed: bool                            # True = no ungrounded evidence claims found


class GroundingGuard:
    """
    Per-conversation-turn grounding validator.

    Usage in bms_llm_agent.py:
        guard = GroundingGuard()
        # After each tool call:
        guard.register_tool_result("predict_maintenance", result)
        # Before returning response:
        audit = guard.audit(final_advice)
        final_advice = audit.clean_text
        if not audit.passed:
            logger.warning(f"[GroundingGuard] {len(audit.ungrounded_claims)} ungrounded claims")
    """

    # Tool results that explicitly signal "no data" — numbers in these must not be cited
    _NO_DATA_SIGNALS = {"no_data", "error", "not_found", "unavailable"}

    def __init__(self) -> None:
        self._tool_results: List[Dict[str, Any]] = []
        self._grounded_numbers: Set[str] = set()   # normalized numeric strings from tool results
        self._no_data_tools: Set[str] = set()       # tools that returned no_data this turn

    # ── Registration ──────────────────────────────────────────────────────────

    def register_tool_result(self, tool_name: str, result: Any) -> None:
        """Call this after every tool execution in the current turn."""
        if not isinstance(result, dict):
            return
        self._tool_results.append({"tool": tool_name, "result": result})

        # If tool returned no_data/error, track it
        if result.get("error") == "no_data" or "error" in result:
            self._no_data_tools.add(tool_name)
            return

        # Walk the result dict and collect all numeric values
        self._extract_numbers(result, tool_name)

    def _extract_numbers(self, obj: Any, tool_name: str, depth: int = 0) -> None:
        """Recursively extract numeric values from tool result."""
        if depth > 6:
            return
        if isinstance(obj, (int, float)):
            self._grounded_numbers.add(self._norm(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                self._extract_numbers(v, tool_name, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                self._extract_numbers(item, tool_name, depth + 1)
        elif isinstance(obj, str):
            # Extract numbers from strings like "85.2 kWh"
            for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", obj):
                self._grounded_numbers.add(self._norm(float(m.group(1))))

    @staticmethod
    def _norm(v: Any) -> str:
        """Normalize a number to a canonical string for comparison."""
        try:
            f = float(v)
            # Round to 1 decimal for fuzzy match (12.3% ≈ tool result 12.3456)
            return f"{round(f, 1)}"
        except (ValueError, TypeError):
            return str(v)

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit(self, response_text: str) -> AuditResult:
        """
        Scan response_text for cited evidence numbers.
        Return AuditResult with any ungrounded claims flagged.
        """
        ungrounded: List[UngroundedClaim] = []
        grounded_tools_used: Set[str] = set()

        for pattern_type, pattern in _EVIDENCE_PATTERNS:
            for match in pattern.finditer(response_text):
                cited_text = match.group(0)

                # Skip if this looks like a safe contextual number
                # Check surrounding context (20 chars before)
                start = max(0, match.start() - 20)
                context = response_text[start:match.end()]
                if _SAFE_CONTEXTS.search(context):
                    continue

                # Extract the numeric value from the match
                numeric = self._extract_numeric_from_match(match)
                if numeric is None:
                    continue

                # Check provenance
                norm_val = self._norm(numeric)
                if self._is_grounded(numeric, norm_val):
                    # Find which tool provided it
                    for tr in self._tool_results:
                        grounded_tools_used.add(tr["tool"])
                else:
                    ungrounded.append(UngroundedClaim(
                        pattern_type=pattern_type,
                        cited_text=cited_text,
                        numeric=numeric,
                    ))

        passed = len(ungrounded) == 0
        clean_text = response_text

        if ungrounded:
            # Log all ungrounded claims
            for claim in ungrounded:
                logger.warning(
                    f"[GroundingGuard] UNGROUNDED CLAIM: type={claim.pattern_type} "
                    f"cited='{claim.cited_text}' value={claim.numeric}"
                )

            # Append a structural disclaimer — operator sees it
            types_cited = ", ".join(sorted({c.pattern_type for c in ungrounded}))
            disclaimer = (
                f"\n\n---\n"
                f"**⚠️ Data Integrity Notice:** {len(ungrounded)} figure(s) in this response "
                f"({types_cited}) could not be traced to live BMS tool results this session. "
                f"Treat those numbers as estimates only — verify against Desigo CC before acting."
            )
            clean_text = response_text + disclaimer

        return AuditResult(
            original_text=response_text,
            clean_text=clean_text,
            ungrounded_claims=ungrounded,
            grounded_values_used=sorted(grounded_tools_used),
            passed=passed,
        )

    def _is_grounded(self, numeric: float, norm_val: str) -> bool:
        """Check if numeric value exists in tool results (exact-match only)."""
        if norm_val in self._grounded_numbers:
            return True
        # Exact match after normalization — no ±5% amnesty
        for grounded_str in self._grounded_numbers:
            try:
                g = float(grounded_str)
                if round(numeric, 1) == round(g, 1):
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _extract_numeric_from_match(match: re.Match) -> Optional[float]:
        """Pull the primary numeric value from a regex match."""
        for g in match.groups():
            if g is not None:
                cleaned = g.replace(",", "")
                try:
                    return float(cleaned)
                except ValueError:
                    continue
        # Try the whole match
        nums = re.findall(r"[\d,]+(?:\.\d+)?", match.group(0))
        for n in nums:
            try:
                return float(n.replace(",", ""))
            except ValueError:
                continue
        return None

    def reset(self) -> None:
        """Reset for a new conversation turn."""
        self._tool_results.clear()
        self._grounded_numbers.clear()
        self._no_data_tools.clear()
