"""
ARVIS Intent Classifier — LLM-First Query Routing
=================================================

Replaces the legacy regex pre-filters in `queen.py` with a single LLM call
that classifies any query into one of six intent classes. Regex fallback
remains as a safety net for LLM failures / timeouts / cold-start.

Six classes (mutually exclusive):
    write_attempt        — operator commanding BMS state change (read-only refusal)
    capability_question  — operator asking what ARVIS can do
    lookup               — simple status / value / list / history retrieval
    diagnostic           — root-cause / trend / "why" / anomaly investigation
    actionable_advisory  — operator asks for a recommendation (read-only advice)
    safety_critical      — fire / leak / evac / hazard (force T3)

Risk tier derives deterministically from intent class. Caller (queen.py)
uses both the class (for routing) and tier (for verification depth).

Cost: one Nova Lite call per query, ~0.0001 USD. Bedrock prompt cache
keeps the example set warm so subsequent queries within 5 minutes hit
cached tokens. Session-level LRU cache (60s TTL) skips classifier entirely
on duplicate queries.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.swarm.intent")


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    """Output of IntentClassifier.classify()."""
    intent_class: str           # one of six classes
    risk_tier: int              # 1, 2, or 3
    confidence: float           # 0.0–1.0
    reason: str                 # short explanation, fits in audit log
    source: str = "llm"         # "llm" | "regex_fallback" | "cache"
    elapsed_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "intent_class": self.intent_class,
            "risk_tier": self.risk_tier,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "source": self.source,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


# Deterministic tier map. Single source of truth; do not duplicate elsewhere.
_TIER_BY_CLASS: Dict[str, int] = {
    "write_attempt":        1,
    "capability_question":  1,
    "lookup":               1,
    "diagnostic":           2,
    "actionable_advisory":  3,
    "safety_critical":      3,
}

_VALID_CLASSES = set(_TIER_BY_CLASS.keys())

DEFAULT_EXAMPLES_YAML = Path(__file__).parent / "intent_examples.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# Regex fallback — kept narrow, only used when LLM fails
# ─────────────────────────────────────────────────────────────────────────────

_REGEX_FALLBACK = [
    # (intent_class, compiled_regex, confidence)
    ("safety_critical", re.compile(
        r"\b(fire\s+alarm|evacuat\w+|smoke\s+detect|refrigerant\s+leak|gas\s+leak|"
        r"sprinkler|lift\s+entrapment|hazard\w*|emergency|life[\s\-]?safety)\b",
        re.IGNORECASE,
    ), 0.85),
    ("capability_question", re.compile(
        r"\b(can\s+you\s+(?:write|modify|change|set|push|command|control)|"
        r"are\s+you\s+(?:read.only|connected|integrated)|"
        r"do\s+you\s+have\s+(?:write|control|access)|"
        r"what\s+(?:can|do)\s+you\s+(?:write|control|actuate))\b",
        re.IGNORECASE,
    ), 0.75),
    ("write_attempt", re.compile(
        # Imperative verb followed by BMS-equipment noun within 120 chars.
        # Intentionally broad to catch most write attempts on the regex path.
        r"\b(?:write|set|change|adjust|modify|push|send|command|control|apply|"
        r"execute|implement|lower|raise|increase|decrease|bump|drop|reduce|"
        r"boost|tweak|tune|enable|disable|turn\s+(?:on|off)|switch\s+(?:on|off)|"
        r"start|stop|restart|reboot|cycle|reset|open|close|"
        r"override|force|bypass|engage|disengage|kill)\b"
        r"(?=.{0,120}\b(?:desigo|bms|bacnet|setpoint|set\s*point|"
        r"chiller|chillers|ch[\-\s]?\d+|ahu[\-\s]?\d*|vav[\-\s\-]*[\d\-]*|fcu[\-\s\-]*[\d\-]*|"
        r"pump|tower|cooling\s+tower|valve|damper|"
        r"zone|zones|floor|floors|"
        r"sp\b|sat\b|chws[t]?\b|cw[rs]?\b|"
        r"temperature|temp\b|pressure|fan|cooling|heating|schedule)\b)",
        re.IGNORECASE,
    ), 0.70),
    ("diagnostic", re.compile(
        r"\b(why\s+is|what's\s+causing|root\s+cause|anomal\w+|trend|"
        r"anything\s+(?:flagging|abnormal|unusual|wrong)|"
        r"investigate|diagnose|pattern\s+in)\b",
        re.IGNORECASE,
    ), 0.70),
    ("actionable_advisory", re.compile(
        r"\b(how\s+should\s+we|should\s+we|recommend|optimi[sz]e|"
        r"best\s+(?:way|strategy|approach)|"
        r"what\s+sequence)\b",
        re.IGNORECASE,
    ), 0.65),
    ("lookup", re.compile(
        r"\b(what\s+is|what's|show\s+me|list|give\s+me|tell\s+me|current|"
        r"status\s+of|reading|history)\b",
        re.IGNORECASE,
    ), 0.55),
]


def _regex_fallback_classify(query: str) -> IntentResult:
    """Pure-regex classifier used when the LLM path fails."""
    for cls, pattern, conf in _REGEX_FALLBACK:
        if pattern.search(query):
            return IntentResult(
                intent_class=cls,
                risk_tier=_TIER_BY_CLASS[cls],
                confidence=conf,
                reason=f"Regex fallback matched pattern for '{cls}'",
                source="regex_fallback",
            )
    # No regex match → safest default is diagnostic (T2 with verification)
    return IntentResult(
        intent_class="diagnostic",
        risk_tier=2,
        confidence=0.30,
        reason="No regex match; defaulting to diagnostic/T2 (safe default)",
        source="regex_fallback",
    )


# ─────────────────────────────────────────────────────────────────────────────
# YAML example loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_examples(path: Path = DEFAULT_EXAMPLES_YAML) -> Dict[str, Any]:
    """Load and validate the YAML example set. Returns {} on failure (LLM
    classifier still works, just with no few-shot anchoring)."""
    if not path.exists():
        logger.warning(f"[IntentClassifier] examples YAML not found at {path}")
        return {}
    try:
        import yaml  # PyYAML
    except ImportError:
        logger.warning("[IntentClassifier] PyYAML not installed — running without few-shot examples")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        classes = data.get("classes", {})
        # Validate each class has examples list
        for cls, body in classes.items():
            if cls not in _VALID_CLASSES:
                logger.warning(f"[IntentClassifier] unknown class '{cls}' in examples — ignored")
                continue
            if not isinstance(body.get("examples"), list):
                logger.warning(f"[IntentClassifier] class '{cls}' missing examples list")
        return classes
    except Exception as e:
        logger.warning(f"[IntentClassifier] failed to parse examples YAML: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# LRU cache — small, in-process, time-bounded
# ─────────────────────────────────────────────────────────────────────────────

class _IntentCache:
    """Tiny LRU keyed by sha1(query.strip().lower()). 60-second TTL."""

    def __init__(self, max_entries: int = 256, ttl_seconds: float = 60.0):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, IntentResult]] = {}

    @staticmethod
    def _key(query: str, history_hash: str = "") -> str:
        # Fix 12: include conversation history disambiguator so cache hits
        # are conditioned on the recent conversational context, not just query text.
        base = query.strip().lower()
        if history_hash:
            base = f"{base}||{history_hash}"
        return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()

    def get(self, query: str, history_hash: str = "") -> Optional[IntentResult]:
        k = self._key(query, history_hash)
        if k not in self._store:
            return None
        ts, result = self._store[k]
        if time.monotonic() - ts > self._ttl:
            self._store.pop(k, None)
            return None
        # Return a copy with source marked cache
        return IntentResult(
            intent_class=result.intent_class,
            risk_tier=result.risk_tier,
            confidence=result.confidence,
            reason=result.reason,
            source="cache",
            elapsed_ms=0.0,
        )

    def put(self, query: str, result: IntentResult, history_hash: str = "") -> None:
        if len(self._store) >= self._max:
            # Drop oldest by insertion order
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)
        self._store[self._key(query, history_hash)] = (time.monotonic(), result)


# ─────────────────────────────────────────────────────────────────────────────
# Main classifier
# ─────────────────────────────────────────────────────────────────────────────

class IntentClassifier:
    """
    Classifies a query into one of six ARVIS intent classes via a single
    Nova-Lite call. Falls back to regex if the LLM fails or returns low
    confidence.

    Usage:
        clf = IntentClassifier(llm_client)
        result = await clf.classify("Lower CH-02 setpoint")
        # → IntentResult(intent_class='write_attempt', risk_tier=1, ...)
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        examples_path: Path = DEFAULT_EXAMPLES_YAML,
        min_llm_confidence: float = 0.60,
        cache_ttl_seconds: float = 60.0,
        llm_timeout_seconds: float = 4.0,
    ):
        self.llm = llm_client
        self.min_conf = min_llm_confidence
        self.timeout = llm_timeout_seconds
        self._examples = _load_examples(examples_path)
        self._cache = _IntentCache(ttl_seconds=cache_ttl_seconds)
        self._sys_prompt_cached: Optional[str] = None

    def _build_system_prompt(self) -> str:
        """Build the few-shot system prompt once; reused across calls so the
        Bedrock prompt cache stays warm."""
        if self._sys_prompt_cached is not None:
            return self._sys_prompt_cached

        lines: List[str] = [
            "You are an intent classifier for ARVIS, a read-only Building Management System advisory AI.",
            "",
            "Classify the user query into EXACTLY ONE of these six intent classes:",
            "",
        ]
        for cls in [
            "write_attempt", "capability_question", "lookup",
            "diagnostic", "actionable_advisory", "safety_critical",
        ]:
            body = self._examples.get(cls, {})
            desc = body.get("description", "(no description)").strip()
            examples = body.get("examples", [])[:10]  # cap to keep prompt small
            lines.append(f"## {cls}")
            lines.append(desc)
            if examples:
                lines.append("Examples:")
                for ex in examples:
                    lines.append(f"  - {ex}")
            lines.append("")

        lines.extend([
            "Rules:",
            "  1. Output strict JSON only: {\"class\": \"...\", \"confidence\": 0.0-1.0, \"reason\": \"...\"}",
            "  2. \"class\" must be one of the six exact names above.",
            "  3. If the query is a command/imperative against BMS equipment, ALWAYS choose write_attempt.",
            "  4. If the query asks about ARVIS's capabilities, ALWAYS choose capability_question.",
            "  5. Anything safety-critical (fire, leak, evacuation) overrides other classes.",
            "  6. Set confidence honestly. Below 0.6 means you're unsure.",
            "  7. \"reason\" must be one short sentence.",
        ])

        self._sys_prompt_cached = "\n".join(lines)
        return self._sys_prompt_cached

    async def classify(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> IntentResult:
        """
        Main entrypoint. Returns IntentResult.

        Strategy:
          1. Cache hit → return immediately.
          2. LLM call with cached system prompt + few-shot examples.
          3. If LLM result confidence < min_conf OR call fails → regex fallback.
          4. Cache and return.
        """
        if not query or not query.strip():
            return IntentResult(
                intent_class="lookup",
                risk_tier=1,
                confidence=0.0,
                reason="Empty query → default lookup",
                source="regex_fallback",
            )

        # Fix 12: derive disambiguator from last 2 turns of conversation history
        _history_hash = ""
        if conversation_history:
            try:
                last2 = conversation_history[-2:]
                _hist_str = "||".join(
                    f"{m.get('role','')}:{str(m.get('content',''))[:200]}"
                    for m in last2
                )
                _history_hash = hashlib.sha1(_hist_str.encode("utf-8", errors="ignore")).hexdigest()[:12]
            except Exception:
                _history_hash = ""

        # 1. Cache check
        cached = self._cache.get(query, _history_hash)
        if cached is not None:
            return cached

        # 2. LLM call
        t_start = time.monotonic()
        llm_result: Optional[IntentResult] = None
        try:
            llm_result = await asyncio.wait_for(
                self._llm_classify(query, conversation_history or []),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[IntentClassifier] LLM classify timeout >{self.timeout}s for query: {query[:80]}")
        except Exception as e:
            logger.warning(f"[IntentClassifier] LLM classify failed ({type(e).__name__}: {e}) — falling back to regex")

        elapsed_ms = (time.monotonic() - t_start) * 1000.0

        # 3. Confidence gate
        if llm_result is not None and llm_result.confidence >= self.min_conf:
            llm_result.elapsed_ms = elapsed_ms
            self._cache.put(query, llm_result, _history_hash)
            logger.debug(f"[IntentClassifier] LLM verdict {llm_result.as_dict()} for: {query[:80]}")
            return llm_result

        # 4. Fallback path
        fb = _regex_fallback_classify(query)
        fb.elapsed_ms = elapsed_ms
        if llm_result is not None:
            fb.reason = f"LLM low-confidence ({llm_result.confidence:.2f}); regex fallback: {fb.reason}"
        self._cache.put(query, fb, _history_hash)
        logger.debug(f"[IntentClassifier] regex-fallback verdict {fb.as_dict()} for: {query[:80]}")
        return fb

    async def _llm_classify(
        self,
        query: str,
        conversation_history: List[Dict[str, Any]],
    ) -> IntentResult:
        """Make one Nova-Lite JSON call. Caller wraps in timeout."""
        # Light context awareness: include up to last 2 turns for disambiguation
        context_lines: List[str] = []
        for turn in conversation_history[-2:]:
            role = turn.get("role", "user")
            content = str(turn.get("content", ""))[:300]
            context_lines.append(f"[{role}] {content}")
        context_block = "\n".join(context_lines)

        user_msg = query if not context_block else (
            f"Recent conversation:\n{context_block}\n\nNew query: {query}"
        )

        try:
            raw = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{
                    "role": "system",
                    "content": self._build_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }],
                channel="intent_classify",
            )
        except Exception:
            raise

        cls = str(raw.get("class", "")).strip().lower()
        if cls not in _VALID_CLASSES:
            raise ValueError(f"LLM returned unknown class: {cls!r}")
        conf = float(raw.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))
        reason = str(raw.get("reason", ""))[:200]

        return IntentResult(
            intent_class=cls,
            risk_tier=_TIER_BY_CLASS[cls],
            confidence=conf,
            reason=reason or f"LLM classified as {cls}",
            source="llm",
        )
