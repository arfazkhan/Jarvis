"""
Skill Router
============

Phase-2 runtime routing for compiled equipment skills. Maps an incoming alarm or
operator query to the right compiled skill + chapter, chains across dependent
equipment, and overlays building-specific learned knowledge.

Three stages (M5):
  1. Equipment Resolution — explicit key, bound equipment_id, or inferred from the
     query text, mapped to a compiled_skill registry entry.
  2. Topic Classification — alarm type / query intent → a chapter topic, by
     deterministic keyword match (no LLM needed; degrades cleanly).
  3. Chapter Selection — load SKILL.md core + the topic chapter, with a fallback
     chain: topic miss → patterns.md → skill core only; equipment miss → list of
     available skills.

Cross-equipment chaining (M6): from the resolved equipment, walk BMSGraph
upstream/downstream and attach the compiled skill cores of dependent equipment
that also have skills — so a root-cause investigation can reason across systems
under one bounded budget.

Learned overlay (M7): the compiled skill is the manufacturer's lens; the building's
actual behaviour lives in the skillbook. route() overlays
skillbook.get_relevant_skills so learned quirks (e.g. "CH-02 trips above 35°C")
sit alongside — and can override — the static manual.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_commercial.skills.skill_registry import SkillRegistry, RegistryEntry

logger = logging.getLogger("arvis.skills.router")

# alarm/query keyword → chapter topic (deterministic classifier)
_TOPIC_KEYWORDS = {
    "fault-codes": ["fault", "error", "alarm", "trip", "code", "diagnos", "fail", "trouble"],
    "startup": ["start", "power", "boot", "initial", "commission", "restart"],
    "maintenance": ["maintenance", "lubricat", "inspect", "service", "schedule", "clean", "pm"],
    "control-logic": ["control", "logic", "pid", "setpoint", "sequence", "interlock", "tuning"],
    "safety": ["safety", "hazard", "lockout", "emergency", "warning", "entrap", "danger"],
}
DEFAULT_TOPIC = "general"
# Cap on dependent skills attached to a chain, to bound token cost.
MAX_CHAIN = 4
# Chars of each dependent skill core to include in a chain link.
CHAIN_CORE_CHARS = 1200


@dataclass
class RoutedSkill:
    equipment_key: str
    status: str
    confidence: float
    topic: str
    skill_core: str
    chapter: str
    source_file: str
    fallback_used: Optional[str] = None


@dataclass
class ChainLink:
    node: str
    relation: str          # upstream / downstream
    equipment_key: str
    skill_core_excerpt: str


@dataclass
class RouteResult:
    resolved: bool
    primary: Optional[RoutedSkill] = None
    chain: list[ChainLink] = field(default_factory=list)
    learned_overlay: list[dict] = field(default_factory=list)
    available_skills: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "resolved": self.resolved,
            "notes": self.notes,
        }
        if self.primary:
            d["primary"] = {
                "equipment_key": self.primary.equipment_key,
                "status": self.primary.status,
                "confidence": self.primary.confidence,
                "topic": self.primary.topic,
                "skill_core": self.primary.skill_core,
                "chapter": self.primary.chapter,
                "source_file": self.primary.source_file,
                "fallback_used": self.primary.fallback_used,
            }
        if self.chain:
            d["chain"] = [
                {"node": c.node, "relation": c.relation,
                 "equipment_key": c.equipment_key, "skill_core_excerpt": c.skill_core_excerpt}
                for c in self.chain
            ]
        if self.learned_overlay:
            d["learned_overlay"] = self.learned_overlay
        if self.available_skills:
            d["available_skills"] = self.available_skills
        return d


class SkillRouter:
    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        graph: Any = None,
        skillbook: Any = None,
    ) -> None:
        self.registry = registry or SkillRegistry()
        self._graph = graph          # BMSGraph or None (lazy)
        self._skillbook = skillbook  # BuildingSkillbook or None

    # ---- stage 1: equipment resolution -----------------------------------

    def resolve_equipment(
        self, equipment_key: str = "", equipment_id: str = "", query: str = "",
    ) -> Optional[RegistryEntry]:
        if equipment_key:
            e = self.registry.get(equipment_key.strip())
            if e:
                return e
        if equipment_id:
            e = self.registry.get_by_equipment_id(equipment_id.strip())
            if e:
                return e
        # infer from query: match registry keys/ids against query tokens
        if query:
            q = query.lower()
            best = None
            for e in self.registry.list_all():
                key_words = e.equipment_key.replace("-", " ").split()
                score = sum(1 for w in key_words if len(w) > 2 and w in q)
                if e.equipment_id and e.equipment_id.lower() in q:
                    score += 5
                if score and (best is None or score > best[0]):
                    best = (score, e)
            if best:
                return best[1]
        return None

    # ---- stage 2: topic classification -----------------------------------

    @staticmethod
    def classify_topic(alarm_type: str = "", query: str = "") -> str:
        text = f"{alarm_type} {query}".lower()
        if not text.strip():
            return DEFAULT_TOPIC
        scores = {topic: sum(1 for kw in kws if kw in text)
                  for topic, kws in _TOPIC_KEYWORDS.items()}
        best_topic, best_score = max(scores.items(), key=lambda kv: kv[1])
        return best_topic if best_score > 0 else DEFAULT_TOPIC

    # ---- stage 3: chapter selection --------------------------------------

    def select_chapter(self, entry: RegistryEntry, topic: str) -> tuple[str, Optional[str]]:
        skill_dir = Path(entry.skill_dir)
        chapter = self._read(skill_dir / "chapters" / f"{topic}.md")
        if chapter:
            return chapter, None
        # fallback: fault topics → patterns.md
        if topic == "fault-codes":
            patterns = self._read(skill_dir / "patterns.md")
            if patterns:
                return patterns, "patterns.md"
        # fallback: general chapter
        general = self._read(skill_dir / "chapters" / "general.md")
        if general:
            return general, "general-chapter"
        return "", "skill-core-only"

    # ---- orchestration ----------------------------------------------------

    async def route(
        self,
        equipment_key: str = "",
        equipment_id: str = "",
        alarm_type: str = "",
        query: str = "",
        cross_equipment: bool = True,
        overlay_learned: bool = True,
    ) -> RouteResult:
        result = RouteResult(resolved=False)

        entry = self.resolve_equipment(equipment_key, equipment_id, query)
        if entry is None:
            result.notes.append("no compiled skill resolved for the request")
            result.available_skills = [
                {"equipment_key": e.equipment_key, "status": e.status,
                 "confidence": e.confidence, "equipment_id": e.equipment_id}
                for e in self.registry.list_all()
            ]
            return result

        topic = self.classify_topic(alarm_type, query)
        skill_core = self._read(Path(entry.skill_dir) / "SKILL.md") or ""
        chapter, fallback = self.select_chapter(entry, topic)
        result.primary = RoutedSkill(
            equipment_key=entry.equipment_key, status=entry.status,
            confidence=entry.confidence, topic=topic, skill_core=skill_core,
            chapter=chapter, source_file=entry.source_file, fallback_used=fallback,
        )
        result.resolved = True
        if fallback:
            result.notes.append(f"chapter fallback: {fallback}")

        if cross_equipment:
            result.chain = self._build_chain(entry, equipment_id)

        if overlay_learned:
            result.learned_overlay = await self._overlay_learned(entry, equipment_id, query)

        logger.info("Routed %s topic=%s chain=%d overlay=%d",
                    entry.equipment_key, topic, len(result.chain), len(result.learned_overlay))
        return result

    # ---- M6: cross-equipment chaining ------------------------------------

    def _get_graph(self):
        if self._graph is None:
            try:
                from agent_commercial.graph import BMSGraph
                self._graph = BMSGraph()
            except Exception as e:
                logger.debug("BMSGraph unavailable: %s", e)
                self._graph = False
        return self._graph or None

    def _build_chain(self, entry: RegistryEntry, equipment_id: str) -> list[ChainLink]:
        graph = self._get_graph()
        if graph is None:
            return []
        # Node to walk from: bound equipment_id if present, else the key's head
        # token (e.g. 'chiller-carrier-30xa' → 'chiller') to match the type graph.
        node = equipment_id.strip() or entry.equipment_key.split("-")[0]
        try:
            up = list(graph.get_upstream(node))
            down = list(graph.get_downstream(node))
        except Exception:
            return []

        links: list[ChainLink] = []
        for rel, nodes in (("upstream", up), ("downstream", down)):
            for n in nodes:
                if len(links) >= MAX_CHAIN:
                    break
                dep = self._resolve_node_skill(n)
                if dep is None:
                    continue
                core = self._read(Path(dep.skill_dir) / "SKILL.md") or ""
                links.append(ChainLink(
                    node=n, relation=rel, equipment_key=dep.equipment_key,
                    skill_core_excerpt=core[:CHAIN_CORE_CHARS],
                ))
        return links

    def _resolve_node_skill(self, node: str) -> Optional[RegistryEntry]:
        """Map a graph node (equipment id or type) to a compiled skill entry."""
        e = self.registry.get_by_equipment_id(node)
        if e:
            return e
        node_l = node.lower()
        for e in self.registry.list_all():
            if node_l in e.equipment_key.lower():
                return e
        return None

    # ---- M7: learned overlay ---------------------------------------------

    def _get_skillbook(self):
        if self._skillbook is None:
            try:
                from agent_commercial.skillbook import get_skillbook
                self._skillbook = get_skillbook(self.registry and "default" or "default")
            except Exception as e:
                logger.debug("Skillbook unavailable: %s", e)
                self._skillbook = False
        return self._skillbook or None

    async def _overlay_learned(self, entry: RegistryEntry, equipment_id: str, query: str) -> list[dict]:
        sb = self._get_skillbook()
        if sb is None:
            return []
        context = {"query": query}
        if equipment_id:
            context["equipment_id"] = equipment_id
        try:
            skills = await sb.get_relevant_skills(context, limit=5)
        except Exception as e:
            logger.debug("learned overlay failed: %s", e)
            return []
        overlay = []
        for s in skills:
            try:
                overlay.append({
                    "title": getattr(s, "title", ""),
                    "description": getattr(s, "description", ""),
                    "confidence": getattr(s, "confidence", None),
                    "equipment_id": getattr(s, "equipment_id", None),
                    "source": "skillbook-learned",
                })
            except Exception:
                continue
        return overlay

    # ---- io ---------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""
