"""
Skill Analyzer
==============

Stage 2 of the manual→skill compiler. Takes the page-marked text from
ManualExtractor and produces a structured CompiledSkill: named fault frameworks,
critical parameters, decision rules, anti-patterns, and per-functional-area
chapters — every item carrying the source page(s) it was derived from.

Design notes:
  * A 228-page manual will not fit one context. The analyzer segments the
    page-marked text by a token budget and runs a map step per segment, then a
    reduce step that synthesizes the SKILL.md core and dedupes frameworks.
  * Source-page discipline is enforced structurally: the extraction schema
    REQUIRES a `source_pages` list on every item. Items the model returns
    without page refs are dropped here and counted, so the M3 grounding gate
    sees only citeable items. (The gate is the hard enforcement; this is the
    first filter.)
  * The client is resolved independently from env vars (frontier/quality model
    preferred for compile), mirroring bms_llm_agent's provider list.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger("arvis.skills.analyzer")

# Compile is a batch job — quality over cost. Prefer a capable model.
# (provider, env_var, base_url, default_model)
_COMPILE_PROVIDERS = [
    ("openai", "OPENAI_API_KEY", None, "gpt-4o"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
     "anthropic/claude-3.5-sonnet"),
    ("k2think", "K2THINK_API_KEY", "https://api.k2think.ai/v2", "MBZUAI-IFM/K2-Think"),
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
]

# Segment budget in chars (~4 chars/token). Keep headroom for prompt + output.
SEGMENT_CHARS = 24000
SEGMENT_OVERLAP = 1500


@dataclass
class Framework:
    name: str
    description: str
    when_applies: str
    source_pages: list[int] = field(default_factory=list)


@dataclass
class CriticalParameter:
    name: str
    normal_range: str
    deviation_implication: str
    source_pages: list[int] = field(default_factory=list)


@dataclass
class DecisionRule:
    condition: str
    action: str
    source_pages: list[int] = field(default_factory=list)


@dataclass
class AntiPattern:
    warning: str
    consequence: str
    source_pages: list[int] = field(default_factory=list)


@dataclass
class FaultPattern:
    name: str
    symptom_signature: str
    diagnostic_steps: str
    root_cause: str
    resolution: str
    source_pages: list[int] = field(default_factory=list)


@dataclass
class CompiledSkill:
    equipment_name: str
    frameworks: list[Framework] = field(default_factory=list)
    critical_parameters: list[CriticalParameter] = field(default_factory=list)
    decision_rules: list[DecisionRule] = field(default_factory=list)
    anti_patterns: list[AntiPattern] = field(default_factory=list)
    fault_patterns: list[FaultPattern] = field(default_factory=list)
    chapters: dict[str, str] = field(default_factory=dict)  # topic -> markdown
    glossary: dict[str, str] = field(default_factory=dict)
    # bookkeeping
    dropped_uncited: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class SkillAnalyzer:
    def __init__(self, model: str | None = None) -> None:
        self._client = None
        self._model = model
        self._provider = None
        self._pool = None  # GroqKeyPool when Groq keys are present
        self._resolve_client()

    def _resolve_client(self) -> None:
        try:
            from openai import OpenAI
        except Exception:
            logger.warning("openai package unavailable; analyzer disabled")
            return
        # Prefer the shared Groq key pool (rotates on rate limits) when Groq keys
        # are configured — the workhorse for compile.
        try:
            from agent_commercial.skills.groq_pool import GroqKeyPool
            pool = GroqKeyPool()
            if pool.available:
                self._pool = pool
                self._provider = "groq"
                self._model = self._model or "llama-3.3-70b-versatile"
                logger.info("Analyzer using Groq key pool (%d keys) model=%s",
                            pool.size, self._model)
                return
        except Exception as e:
            logger.debug("Groq pool init skipped: %s", e)
        for provider, env_var, base_url, default_model in _COMPILE_PROVIDERS:
            key = os.getenv(env_var, "").strip()
            if not key:
                continue
            kwargs = {"api_key": key}
            if base_url:
                kwargs["base_url"] = base_url
            try:
                self._client = OpenAI(**kwargs)
                self._model = self._model or default_model
                self._provider = provider
                logger.info("Analyzer using provider=%s model=%s", provider, self._model)
                return
            except Exception as e:
                logger.warning("Analyzer provider %s init failed: %s", provider, e)
        logger.warning("No compile LLM key found; analyzer cannot run")

    @property
    def available(self) -> bool:
        return self._client is not None or self._pool is not None

    # ---- segmentation -----------------------------------------------------

    @staticmethod
    def _segment(text: str) -> list[str]:
        segments = []
        i = 0
        n = len(text)
        while i < n:
            end = min(i + SEGMENT_CHARS, n)
            # try to break on a page marker boundary for clean cites
            if end < n:
                nxt = text.rfind("\n===== PAGE", i, end)
                if nxt > i + SEGMENT_CHARS // 2:
                    end = nxt
            segments.append(text[i:end])
            if end >= n:
                break
            i = max(end - SEGMENT_OVERLAP, i + 1)
        return segments

    # ---- LLM plumbing -----------------------------------------------------

    def _chat_json(self, system: str, user: str) -> dict[str, Any]:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        if self._pool is not None:
            resp = self._pool.chat_completion(
                model=self._model, messages=messages, temperature=0.0, max_tokens=4096)
            return self._parse_json((resp.choices[0].message.content or "").strip())
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.0,
            max_tokens=4096,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        # tolerate ```json fences and leading prose
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
        else:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
        try:
            return json.loads(raw)
        except Exception as e:
            logger.warning("JSON parse failed: %s | head=%s", e, raw[:200])
            return {}

    # ---- map: extract structured items per segment ------------------------

    _MAP_SYSTEM = (
        "You extract reasoning-ready structures from an equipment manual segment. "
        "You NEVER invent facts. Every item MUST include source_pages: the PAGE "
        "numbers (from the ===== PAGE N ===== markers) the item is derived from. "
        "If you cannot attribute an item to a page, DO NOT include it. Return only "
        "JSON."
    )

    _MAP_SCHEMA = """Return JSON:
{
  "frameworks": [{"name","description","when_applies","source_pages":[int]}],
  "critical_parameters": [{"name","normal_range","deviation_implication","source_pages":[int]}],
  "decision_rules": [{"condition","action","source_pages":[int]}],
  "anti_patterns": [{"warning","consequence","source_pages":[int]}],
  "fault_patterns": [{"name","symptom_signature","diagnostic_steps","root_cause","resolution","source_pages":[int]}],
  "glossary": {"term":"definition with normal range if applicable"}
}
Omit empty arrays' items rather than fabricating. Only include what the text supports."""

    def _map_segment(self, segment: str) -> dict[str, Any]:
        user = f"{self._MAP_SCHEMA}\n\nMANUAL SEGMENT:\n{segment}"
        return self._chat_json(self._MAP_SYSTEM, user)

    # ---- reduce: merge, drop uncited, assign chapters ---------------------

    def analyze(self, equipment_name: str, page_marked_text: str) -> CompiledSkill:
        if not self.available:
            raise RuntimeError("SkillAnalyzer has no LLM client (set a compile API key)")

        skill = CompiledSkill(equipment_name=equipment_name, model=self._model or "")
        segments = self._segment(page_marked_text)
        logger.info("Analyzing %s in %d segments", equipment_name, len(segments))

        for idx, seg in enumerate(segments):
            try:
                data = self._map_segment(seg)
            except Exception as e:
                logger.warning("Segment %d analysis failed: %s", idx, e)
                continue
            self._merge_segment(skill, data)

        self._dedupe(skill)
        self._assign_chapters(skill)
        logger.info(
            "Compiled %s: %d frameworks, %d params, %d rules, %d anti, %d fault-patterns (dropped %d uncited)",
            equipment_name, len(skill.frameworks), len(skill.critical_parameters),
            len(skill.decision_rules), len(skill.anti_patterns),
            len(skill.fault_patterns), skill.dropped_uncited,
        )
        return skill

    def _merge_segment(self, skill: CompiledSkill, data: dict[str, Any]) -> None:
        def cited(item: dict) -> bool:
            pages = item.get("source_pages") or []
            ok = isinstance(pages, list) and any(isinstance(p, int) for p in pages)
            if not ok:
                skill.dropped_uncited += 1
            return ok

        for f in data.get("frameworks", []) or []:
            if cited(f):
                skill.frameworks.append(Framework(
                    name=f.get("name", "").strip(),
                    description=f.get("description", "").strip(),
                    when_applies=f.get("when_applies", "").strip(),
                    source_pages=[p for p in f["source_pages"] if isinstance(p, int)],
                ))
        for p in data.get("critical_parameters", []) or []:
            if cited(p):
                skill.critical_parameters.append(CriticalParameter(
                    name=p.get("name", "").strip(),
                    normal_range=p.get("normal_range", "").strip(),
                    deviation_implication=p.get("deviation_implication", "").strip(),
                    source_pages=[x for x in p["source_pages"] if isinstance(x, int)],
                ))
        for r in data.get("decision_rules", []) or []:
            if cited(r):
                skill.decision_rules.append(DecisionRule(
                    condition=r.get("condition", "").strip(),
                    action=r.get("action", "").strip(),
                    source_pages=[x for x in r["source_pages"] if isinstance(x, int)],
                ))
        for a in data.get("anti_patterns", []) or []:
            if cited(a):
                skill.anti_patterns.append(AntiPattern(
                    warning=a.get("warning", "").strip(),
                    consequence=a.get("consequence", "").strip(),
                    source_pages=[x for x in a["source_pages"] if isinstance(x, int)],
                ))
        for fp in data.get("fault_patterns", []) or []:
            if cited(fp):
                skill.fault_patterns.append(FaultPattern(
                    name=fp.get("name", "").strip(),
                    symptom_signature=fp.get("symptom_signature", "").strip(),
                    diagnostic_steps=fp.get("diagnostic_steps", "").strip(),
                    root_cause=fp.get("root_cause", "").strip(),
                    resolution=fp.get("resolution", "").strip(),
                    source_pages=[x for x in fp["source_pages"] if isinstance(x, int)],
                ))
        for term, definition in (data.get("glossary") or {}).items():
            if term and term not in skill.glossary:
                skill.glossary[term] = definition

    @staticmethod
    def _dedupe(skill: CompiledSkill) -> None:
        def merge_by_name(items, key):
            seen = {}
            for it in items:
                k = getattr(it, key).lower().strip()
                if not k:
                    continue
                if k in seen:
                    seen[k].source_pages = sorted(set(seen[k].source_pages + it.source_pages))
                else:
                    seen[k] = it
            return list(seen.values())
        skill.frameworks = merge_by_name(skill.frameworks, "name")
        skill.critical_parameters = merge_by_name(skill.critical_parameters, "name")
        skill.anti_patterns = merge_by_name(skill.anti_patterns, "warning")
        skill.fault_patterns = merge_by_name(skill.fault_patterns, "name")

    # Topic buckets → chapter files.
    _TOPIC_KEYWORDS = {
        "fault-codes": ["fault", "error", "alarm", "trip", "code", "diagnos"],
        "startup": ["start", "power", "boot", "initial", "commission"],
        "maintenance": ["maintenance", "lubricat", "inspect", "service", "schedule", "clean"],
        "control-logic": ["control", "logic", "pid", "setpoint", "sequence", "interlock"],
        "safety": ["safety", "hazard", "lockout", "emergency", "warning"],
    }

    def _assign_chapters(self, skill: CompiledSkill) -> None:
        """Render markdown chapter bodies by bucketing items into topic areas."""
        buckets: dict[str, list[str]] = {t: [] for t in self._TOPIC_KEYWORDS}
        buckets["general"] = []

        def topic_of(text: str) -> str:
            t = text.lower()
            for topic, kws in self._TOPIC_KEYWORDS.items():
                if any(kw in t for kw in kws):
                    return topic
            return "general"

        for fp in skill.fault_patterns:
            body = (f"### {fp.name}\n"
                    f"- **Symptom:** {fp.symptom_signature}\n"
                    f"- **Diagnose:** {fp.diagnostic_steps}\n"
                    f"- **Root cause:** {fp.root_cause}\n"
                    f"- **Resolution:** {fp.resolution}\n"
                    f"- _pages: {fp.source_pages}_")
            buckets[topic_of(fp.name + fp.symptom_signature)].append(body)
        for r in skill.decision_rules:
            buckets[topic_of(r.condition + r.action)].append(
                f"- IF {r.condition} → {r.action} _(pages {r.source_pages})_")
        for a in skill.anti_patterns:
            buckets["safety"].append(
                f"- ⚠️ {a.warning} → {a.consequence} _(pages {a.source_pages})_")

        for topic, lines in buckets.items():
            if lines:
                skill.chapters[topic] = f"# {topic}\n\n" + "\n\n".join(lines)
